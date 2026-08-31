from __future__ import annotations

import logging
import os
import re
import time

import requests
from flask import Flask, abort, jsonify, render_template, request

from .audit import audit_rules, audit_tree
from .github import GitHubAppClient
from .security import verify_signature

LOGGER = logging.getLogger("qnode")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
PULL_REQUEST_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        GITHUB_APP_ID=os.getenv("GITHUB_APP_ID", ""),
        GITHUB_PRIVATE_KEY=os.getenv("GITHUB_PRIVATE_KEY", ""),
        GITHUB_PRIVATE_KEY_PATH=os.getenv("GITHUB_PRIVATE_KEY_PATH", ""),
        GITHUB_INSTALLATION_ID=os.getenv("GITHUB_INSTALLATION_ID", ""),
        GITHUB_PUBLIC_TOKEN=os.getenv("GITHUB_PUBLIC_TOKEN", ""),
        GITHUB_WEBHOOK_SECRET=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
        PUBLIC_AUDIT_ENABLED=os.getenv("PUBLIC_AUDIT_ENABLED", "true").lower() == "true",
        AUDIT_CACHE_SECONDS=int(os.getenv("AUDIT_CACHE_SECONDS", "300")),
    )
    if config:
        app.config.update(config)

    public_cache: dict[tuple[str, str], tuple[float, dict]] = {}
    processed_deliveries: dict[str, float] = {}

    def github_client() -> GitHubAppClient:
        return GitHubAppClient(
            app_id=app.config["GITHUB_APP_ID"],
            private_key=app.config["GITHUB_PRIVATE_KEY"],
            private_key_path=app.config["GITHUB_PRIVATE_KEY_PATH"],
        )

    def installation_token(client: GitHubAppClient, payload: dict) -> str:
        installation_id = (payload.get("installation") or {}).get("id")
        installation_id = installation_id or app.config["GITHUB_INSTALLATION_ID"]
        if not installation_id:
            abort(503, description="GitHub App installation is not configured")
        return client.installation_token(int(installation_id))

    def run_installed_audit(
        client: GitHubAppClient,
        repository: str,
        sha: str,
        token: str,
        pull_number: int | None = None,
    ):
        snapshot = client.tree_snapshot(repository, sha, token)
        changed_files = (
            client.pull_request_files(repository, pull_number, token) if pull_number else []
        )
        audit = audit_tree(
            snapshot.paths,
            changed_files,
            tree_truncated=snapshot.truncated,
        )
        client.publish_check(repository, sha, audit, token)
        return audit

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
            "frame-ancestors 'none'",
        )
        return response

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            public_audit_enabled=app.config["PUBLIC_AUDIT_ENABLED"],
        )

    @app.get("/health")
    def health():
        return jsonify(
            status="ready",
            service="qnode-repo-auditor",
            version="0.2.0",
            public_audit=bool(app.config["PUBLIC_AUDIT_ENABLED"]),
            webhook_configured=bool(app.config["GITHUB_WEBHOOK_SECRET"]),
        )

    @app.get("/api/rules")
    def rules():
        return jsonify(rules=audit_rules(), total_weight=100)

    @app.route("/api/audit", methods=["GET", "POST"])
    def public_audit():
        if not app.config["PUBLIC_AUDIT_ENABLED"]:
            abort(404)

        values = request.get_json(silent=True) if request.method == "POST" else request.args
        values = values or {}
        repository = str(values.get("repository", "")).strip()
        requested_ref = str(values.get("ref", "")).strip()
        if not REPOSITORY_PATTERN.fullmatch(repository):
            return jsonify(error="Use a repository in owner/name format."), 400
        if requested_ref and (
            not REF_PATTERN.fullmatch(requested_ref)
            or ".." in requested_ref
            or requested_ref.startswith("/")
        ):
            return jsonify(error="The requested Git ref is not valid."), 400

        cache_ref = requested_ref or "@default"
        cache_key = (repository.lower(), cache_ref)
        cached = public_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < app.config["AUDIT_CACHE_SECONDS"]:
            response = dict(cached[1])
            response["cached"] = True
            return jsonify(response)

        try:
            client = github_client()
            token = app.config["GITHUB_PUBLIC_TOKEN"]
            info = client.repository_info(repository, token)
            ref = requested_ref or info["default_branch"]
            snapshot = client.tree_snapshot(repository, ref, token)
            audit = audit_tree(snapshot.paths, tree_truncated=snapshot.truncated)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else 502
            if status == 404:
                return jsonify(error="Repository or ref not found, or it is not public."), 404
            if status in {403, 429}:
                return jsonify(error="GitHub API rate limit reached. Try again later."), 429
            LOGGER.warning("Public GitHub audit failed: %s", error)
            return jsonify(error="GitHub could not complete the audit."), 502
        except requests.RequestException as error:
            LOGGER.warning("Public GitHub audit network failure: %s", error)
            return jsonify(error="GitHub is temporarily unreachable."), 502

        response = {
            "repository": info,
            "ref": ref,
            "scanned_paths": len(snapshot.paths),
            "cached": False,
            "audit": audit.to_dict(),
        }
        public_cache[cache_key] = (time.monotonic(), response)
        if len(public_cache) > 256:
            oldest = min(public_cache, key=lambda key: public_cache[key][0])
            public_cache.pop(oldest, None)
        return jsonify(response)

    @app.post("/webhook")
    def webhook():
        raw = request.get_data()
        if not verify_signature(
            raw,
            request.headers.get("X-Hub-Signature-256"),
            app.config["GITHUB_WEBHOOK_SECRET"],
        ):
            abort(401)

        event = request.headers.get("X-GitHub-Event", "")
        delivery = request.headers.get("X-GitHub-Delivery", "")
        payload = request.get_json(silent=True) or {}
        if event == "ping":
            return jsonify(ok=True, message="QNode channel open")

        if delivery and delivery in processed_deliveries:
            return jsonify(ok=True, duplicate=True)

        client = github_client()
        if event == "pull_request" and payload.get("action") in PULL_REQUEST_ACTIONS:
            token = installation_token(client, payload)
            try:
                repository = payload["repository"]["full_name"]
                pull = payload["pull_request"]
                sha = pull["head"]["sha"]
                number = int(payload.get("number") or pull["number"])
            except (KeyError, TypeError, ValueError):
                abort(400, description="Malformed pull_request payload")
            audit = run_installed_audit(client, repository, sha, token, number)
        elif (
            event == "check_run"
            and payload.get("action") == "requested_action"
            and (payload.get("requested_action") or {}).get("identifier") == "rerun"
        ):
            token = installation_token(client, payload)
            try:
                repository = payload["repository"]["full_name"]
                check_run = payload["check_run"]
                sha = check_run["head_sha"]
                pull_requests = check_run.get("pull_requests") or []
                number = int(pull_requests[0]["number"]) if pull_requests else None
            except (KeyError, TypeError, ValueError):
                abort(400, description="Malformed check_run payload")
            audit = run_installed_audit(client, repository, sha, token, number)
        else:
            return jsonify(ok=True, ignored=True)

        if delivery:
            processed_deliveries[delivery] = time.monotonic()
            if len(processed_deliveries) > 1000:
                cutoff = time.monotonic() - 24 * 60 * 60
                for key, created in list(processed_deliveries.items()):
                    if created < cutoff:
                        processed_deliveries.pop(key, None)

        return jsonify(
            ok=True,
            score=audit.score,
            grade=audit.grade,
            risks=len(audit.risks),
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
