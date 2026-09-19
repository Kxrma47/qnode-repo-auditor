from __future__ import annotations

import logging
import os
import re
import secrets
import sqlite3
import time
from dataclasses import replace
from hmac import compare_digest
from urllib.parse import urlsplit

import requests
from flask import Flask, abort, jsonify, render_template, request

from .analytics import VisitorStore
from .audit import (
    ReviewDelta,
    audit_rules,
    audit_tree,
    compare_review_signals,
    find_codeowners_path,
)
from .github import MAX_PR_FILES, GitHubAppClient, TreeSnapshot, compare_trees
from .policy import POLICY_PATH, AuditPolicy, parse_policy
from .security import validate_secret_strength, verify_signature

LOGGER = logging.getLogger("qnode")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
PULL_PATTERN = re.compile(r"^[1-9][0-9]{0,9}$")
PULL_REQUEST_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}
BROWSER_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")


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
        OWNER_METRICS_TOKEN=os.getenv("OWNER_METRICS_TOKEN", ""),
        OWNER_METRICS_USERNAME=os.getenv("OWNER_METRICS_USERNAME", "Kxrma47"),
        VISITOR_METRICS_DB=os.getenv("VISITOR_METRICS_DB", ""),
    )
    if config:
        app.config.update(config)
    if not app.config["TESTING"]:
        validate_secret_strength("GITHUB_WEBHOOK_SECRET", app.config["GITHUB_WEBHOOK_SECRET"])
        validate_secret_strength("OWNER_METRICS_TOKEN", app.config["OWNER_METRICS_TOKEN"])
        if app.config["GITHUB_PRIVATE_KEY"] or app.config["GITHUB_PRIVATE_KEY_PATH"]:
            GitHubAppClient(
                app_id=app.config["GITHUB_APP_ID"],
                private_key=app.config["GITHUB_PRIVATE_KEY"],
                private_key_path=app.config["GITHUB_PRIVATE_KEY_PATH"],
            )._app_jwt()
    visitor_store = (
        VisitorStore(app.config["VISITOR_METRICS_DB"]) if app.config["VISITOR_METRICS_DB"] else None
    )

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

    def repository_policy(
        client: GitHubAppClient, repository: str, ref: str, token: str, paths: list[str]
    ) -> AuditPolicy:
        if POLICY_PATH not in paths:
            return AuditPolicy()
        content = client.file_text(repository, POLICY_PATH, ref, token)
        if not content:
            return AuditPolicy(
                warning=".qnode.json is empty or could not be read. Using default rules."
            )
        return parse_policy(content)

    def with_review_delta(
        client: GitHubAppClient,
        repository: str,
        number: int,
        pull: dict,
        current_audit,
        current_tree: TreeSnapshot,
        policy: AuditPolicy,
        token: str,
    ):
        """Best-effort comparison; a missing or truncated baseline never becomes a claim."""
        if current_audit.files_truncated or current_tree.truncated or not pull.get("base_sha"):
            return current_audit
        try:
            review = client.latest_submitted_review(repository, number, token)
            if not review:
                return current_audit
            if review["commit_sha"] == pull["head_sha"]:
                return replace(
                    current_audit,
                    review_delta=ReviewDelta(
                        baseline_sha=review["commit_sha"],
                        reviewed_at=review["submitted_at"],
                        changed_paths=(),
                        changed_path_count=0,
                        new_signals=(),
                        resolved_signals=(),
                    ),
                )
            base_tree = client.tree_snapshot(repository, pull["base_sha"], token)
            reviewed_tree = client.tree_snapshot(repository, review["commit_sha"], token)
            previous_files = compare_trees(base_tree, reviewed_tree)
            changed_files = compare_trees(reviewed_tree, current_tree)
            if len(previous_files) > MAX_PR_FILES or len(changed_files) > MAX_PR_FILES:
                return current_audit
            prior_audit = audit_tree(reviewed_tree.paths, previous_files, policy=policy)
            return replace(
                current_audit,
                review_delta=compare_review_signals(
                    prior_audit,
                    current_audit,
                    baseline_sha=review["commit_sha"],
                    reviewed_at=review["submitted_at"],
                    changed_paths=(file.filename for file in changed_files),
                ),
            )
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            LOGGER.warning("Review delta unavailable: %s", type(error).__name__)
            return current_audit

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
        codeowners_path = find_codeowners_path(snapshot.paths)
        codeowners_content = (
            client.file_text(repository, codeowners_path, sha, token) if codeowners_path else ""
        )
        policy = repository_policy(client, repository, sha, token, snapshot.paths)
        audit = audit_tree(
            snapshot.paths,
            changed_files,
            codeowners_content=codeowners_content,
            tree_truncated=snapshot.truncated,
            files_truncated=len(changed_files) >= MAX_PR_FILES,
            policy=policy,
        )
        if pull_number:
            pull = client.pull_request_info(repository, pull_number, token)
            audit = with_review_delta(
                client, repository, pull_number, pull, audit, snapshot, policy, token
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
        response = app.make_response(
            render_template(
                "index.html",
                public_audit_enabled=app.config["PUBLIC_AUDIT_ENABLED"],
                visitor_metrics_enabled=bool(visitor_store),
            )
        )
        if (
            visitor_store
            and request.headers.get("DNT") != "1"
            and not BROWSER_TOKEN_PATTERN.fullmatch(request.cookies.get("qnode_browser", ""))
        ):
            response.set_cookie(
                "qnode_browser",
                secrets.token_hex(16),
                max_age=365 * 24 * 60 * 60,
                secure=not app.config["TESTING"],
                httponly=True,
                samesite="Lax",
            )
        return response

    @app.post("/api/visit")
    def visit():
        if not visitor_store:
            abort(404)
        token = request.cookies.get("qnode_browser", "")
        origin = request.headers.get("Origin", "")
        parsed_origin = urlsplit(origin)
        if (
            not BROWSER_TOKEN_PATTERN.fullmatch(token)
            or request.headers.get("X-QNode-Visit") != "1"
            or (
                origin
                and (
                    parsed_origin.netloc != request.host
                    or parsed_origin.scheme not in {"http", "https"}
                )
            )
            or request.headers.get("DNT") == "1"
        ):
            abort(403)
        try:
            visitor_store.record(token)
        except sqlite3.Error as error:
            LOGGER.warning("Visitor metrics write failed: %s", type(error).__name__)
            return ("", 503, {"Cache-Control": "no-store"})
        return ("", 204, {"Cache-Control": "no-store"})

    @app.get("/health")
    def health():
        return jsonify(
            status="ready",
            service="qnode-repo-auditor",
            version="0.7.1",
            public_audit=bool(app.config["PUBLIC_AUDIT_ENABLED"]),
            webhook_configured=bool(app.config["GITHUB_WEBHOOK_SECRET"]),
            owner_metrics_configured=bool(app.config["OWNER_METRICS_TOKEN"]),
            visitor_metrics_configured=bool(visitor_store),
        )

    @app.get("/owner/metrics")
    def owner_metrics():
        if not app.config["OWNER_METRICS_TOKEN"]:
            abort(404)
        credentials = request.authorization
        username = credentials.username if credentials and credentials.type == "basic" else ""
        password = credentials.password if credentials and credentials.type == "basic" else ""
        if not (
            compare_digest(username or "", app.config["OWNER_METRICS_USERNAME"])
            and compare_digest(password or "", app.config["OWNER_METRICS_TOKEN"])
        ):
            response = app.make_response(("Owner authentication required.", 401))
            response.headers["WWW-Authenticate"] = 'Basic realm="QNode owner metrics"'
        else:
            try:
                installations = github_client().app_installation_count()
            except (requests.RequestException, ValueError) as error:
                LOGGER.warning("Owner metrics fetch failed: %s", type(error).__name__)
                response = app.make_response(("GitHub installation count unavailable.", 502))
            else:
                usage = None
                if visitor_store:
                    try:
                        usage = visitor_store.snapshot()
                    except sqlite3.Error as error:
                        LOGGER.warning("Visitor metrics read failed: %s", type(error).__name__)
                response = app.make_response(
                    render_template(
                        "owner_metrics.html",
                        installations=installations,
                        usage=usage,
                        visitor_metrics_enabled=bool(visitor_store),
                    )
                )
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

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
        requested_pull = str(values.get("pull", "")).strip()
        if not REPOSITORY_PATTERN.fullmatch(repository):
            return jsonify(error="Use a repository in owner/name format."), 400
        if requested_ref and (
            not REF_PATTERN.fullmatch(requested_ref)
            or ".." in requested_ref
            or requested_ref.startswith("/")
        ):
            return jsonify(error="The requested Git ref is not valid."), 400
        if requested_pull and not PULL_PATTERN.fullmatch(requested_pull):
            return jsonify(error="The pull request number is not valid."), 400
        if requested_pull and requested_ref:
            return jsonify(error="Use either a pull request number or a Git ref, not both."), 400

        cache_ref = f"@pull:{requested_pull}" if requested_pull else requested_ref or "@default"
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
            if info["visibility"] != "public":
                return jsonify(error="Repository or ref not found, or it is not public."), 404
            pull = None
            changed_files = []
            if requested_pull:
                pull_number = int(requested_pull)
                pull = client.pull_request_info(repository, pull_number, token)
                ref = pull["head_sha"]
                changed_files = client.pull_request_files(repository, pull_number, token)
            else:
                ref = requested_ref or info["default_branch"]
            snapshot = client.tree_snapshot(repository, ref, token)
            codeowners_path = find_codeowners_path(snapshot.paths)
            codeowners_content = (
                client.file_text(repository, codeowners_path, ref, token) if codeowners_path else ""
            )
            policy = repository_policy(client, repository, ref, token, snapshot.paths)
            audit = audit_tree(
                snapshot.paths,
                changed_files,
                codeowners_content=codeowners_content,
                tree_truncated=snapshot.truncated,
                files_truncated=(
                    bool(pull)
                    and (
                        len(changed_files) >= MAX_PR_FILES
                        or pull["changed_files"] > len(changed_files)
                    )
                ),
                policy=policy,
            )
            if pull:
                audit = with_review_delta(
                    client,
                    repository,
                    pull_number,
                    pull,
                    audit,
                    snapshot,
                    policy,
                    token,
                )
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
        if pull:
            response["pull_request"] = pull
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
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
