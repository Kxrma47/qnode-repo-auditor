from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
import time
from dataclasses import replace
from hmac import compare_digest
from urllib.parse import urlsplit

import psycopg
import requests
from flask import Flask, abort, jsonify, render_template, request

from . import __version__
from .analytics import EVENT_KEYS, PostgresVisitorStore, VisitorStore, metrics_error_category
from .audit import (
    ChangedFile,
    ReviewDelta,
    audit_rules,
    audit_tree,
    compare_review_signals,
    evaluate_change_contracts,
    find_codeowners_path,
)
from .github import MAX_PR_FILES, GitHubAppClient, TreeSnapshot, compare_trees
from .insights import attention_item, ci_evidence, compare_audits, review_handoff
from .intelligence import (
    build_review_intelligence,
    intelligence_markdown,
    reviewer_load_snapshot,
)
from .policy import POLICY_PATH, AuditPolicy, parse_policy
from .security import validate_secret_strength, verify_signature

LOGGER = logging.getLogger("qnode")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
PULL_PATTERN = re.compile(r"^[1-9][0-9]{0,9}$")
PULL_REQUEST_ACTIONS = {"opened", "reopened", "synchronize", "ready_for_review"}
BROWSER_TOKEN_PATTERN = re.compile(r"^[0-9a-f]{32}$")
FEEDBACK_SIGNAL_KEYS = frozenset(
    {
        "source-without-tests",
        "manifest-without-lock",
        "workflow-change",
        "credential-path",
        "large-change",
        "migration-change",
        "critical-path",
        "critical-path-overflow",
    }
)


def valid_ref(value: str) -> bool:
    return bool(REF_PATTERN.fullmatch(value) and ".." not in value and not value.startswith("/"))


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
        VISITOR_METRICS_URL=os.getenv("VISITOR_METRICS_URL", ""),
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
    if app.config["VISITOR_METRICS_DB"] and app.config["VISITOR_METRICS_URL"]:
        raise ValueError("Configure only one visitor metrics backend")
    visitor_store = None
    if app.config["VISITOR_METRICS_URL"]:
        visitor_store = PostgresVisitorStore(app.config["VISITOR_METRICS_URL"])
    elif app.config["VISITOR_METRICS_DB"]:
        visitor_store = VisitorStore(app.config["VISITOR_METRICS_DB"])

    public_cache: dict[tuple[str, str], tuple[float, dict]] = {}
    attention_cache: dict[str, tuple[float, dict]] = {}
    comparison_cache: dict[tuple[str, str, str], tuple[float, dict]] = {}
    followup_cache: dict[tuple[str, int], tuple[float, dict]] = {}
    processed_deliveries: dict[str, float] = {}

    def github_client() -> GitHubAppClient:
        return GitHubAppClient(
            app_id=app.config["GITHUB_APP_ID"],
            private_key=app.config["GITHUB_PRIVATE_KEY"],
            private_key_path=app.config["GITHUB_PRIVATE_KEY_PATH"],
        )

    def record_successful_scan(is_pull_request: bool) -> None:
        if visitor_store and request.headers.get("DNT") != "1":
            try:
                visitor_store.record_scan("pull_request" if is_pull_request else "repository")
            except (sqlite3.Error, psycopg.Error) as error:
                LOGGER.warning("Scan metrics write failed: %s", metrics_error_category(error))

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
        pull = None
        checks = None
        if pull_number:
            pull = client.pull_request_info(repository, pull_number, token)
            audit = with_review_delta(
                client, repository, pull_number, pull, audit, snapshot, policy, token
            )
            try:
                checks = client.check_runs(repository, pull["head_sha"], token)
            except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
                LOGGER.warning("Installed PR check listing unavailable")
        history = []
        reviewer_load = None
        try:
            history = client.recent_commit_paths(repository, sha, token)
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
            LOGGER.warning("Installed filename history unavailable")
        if pull:
            try:
                reviewer_load = reviewer_load_snapshot(
                    client.open_pull_requests(repository, token, limit=30)
                )
            except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
                LOGGER.warning("Installed reviewer load snapshot unavailable")
        ci_data = ci_evidence(checks, audit.to_dict()["review_map"]) if pull else None
        intelligence = build_review_intelligence(
            audit,
            changed_files,
            pull=pull,
            ci=ci_data,
            history=history,
            reviewer_load=reviewer_load,
        )
        client.publish_check(
            repository,
            sha,
            audit,
            token,
            extra_markdown=intelligence_markdown(intelligence),
        )
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
        except (sqlite3.Error, psycopg.Error) as error:
            LOGGER.warning("Visitor metrics write failed: %s", metrics_error_category(error))
            return ("", 503, {"Cache-Control": "no-store"})
        return ("", 204, {"Cache-Control": "no-store"})

    @app.post("/api/signal-feedback")
    def signal_feedback():
        if not app.config["PUBLIC_AUDIT_ENABLED"] or not visitor_store:
            abort(404)
        token = request.cookies.get("qnode_browser", "")
        origin = request.headers.get("Origin", "")
        parsed_origin = urlsplit(origin)
        if (
            not BROWSER_TOKEN_PATTERN.fullmatch(token)
            or request.headers.get("X-QNode-Feedback") != "1"
            or request.headers.get("DNT") == "1"
            or (
                origin
                and (
                    parsed_origin.netloc != request.host
                    or parsed_origin.scheme not in {"http", "https"}
                )
            )
        ):
            abort(403)
        if request.content_length is None or request.content_length > 512 or not request.is_json:
            return jsonify(error="Invalid feedback body."), 400
        values = request.get_json(silent=True)
        if (
            not isinstance(values, dict)
            or set(values) != {"signal", "useful"}
            or not isinstance(values["signal"], str)
            or values["signal"] not in FEEDBACK_SIGNAL_KEYS
            or type(values["useful"]) is not bool
        ):
            return jsonify(error="Choose a reported signal and helpfulness."), 400
        try:
            visitor_store.record_feedback(token, values["signal"], values["useful"])
        except (sqlite3.Error, psycopg.Error) as error:
            LOGGER.warning("Signal feedback write failed: %s", metrics_error_category(error))
            return jsonify(error="Feedback is temporarily unavailable."), 503
        return ("", 204, {"Cache-Control": "no-store"})

    @app.post("/api/event")
    def conversion_event():
        if not visitor_store:
            abort(404)
        token = request.cookies.get("qnode_browser", "")
        origin = request.headers.get("Origin", "")
        parsed_origin = urlsplit(origin)
        if (
            not BROWSER_TOKEN_PATTERN.fullmatch(token)
            or request.headers.get("X-QNode-Event") != "1"
            or request.headers.get("DNT") == "1"
            or (
                origin
                and (
                    parsed_origin.netloc != request.host
                    or parsed_origin.scheme not in {"http", "https"}
                )
            )
        ):
            abort(403)
        if request.content_length is None or request.content_length > 128 or not request.is_json:
            return jsonify(error="Invalid event body."), 400
        values = request.get_json(silent=True)
        if not isinstance(values, dict) or set(values) != {"event"}:
            return jsonify(error="Provide one event."), 400
        event_key = values.get("event")
        if not isinstance(event_key, str) or event_key not in EVENT_KEYS:
            return jsonify(error="Unknown event."), 400
        try:
            visitor_store.record_event(event_key)
        except (sqlite3.Error, psycopg.Error) as error:
            LOGGER.warning("Conversion metric write failed: %s", metrics_error_category(error))
            return ("", 503, {"Cache-Control": "no-store"})
        return ("", 204, {"Cache-Control": "no-store"})

    @app.get("/health")
    def health():
        return jsonify(
            status="ready",
            service="qnode-repo-auditor",
            version=__version__,
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
                feedback = None
                if visitor_store:
                    try:
                        usage = visitor_store.snapshot()
                        feedback = visitor_store.feedback_snapshot()
                    except (sqlite3.Error, psycopg.Error) as error:
                        LOGGER.warning(
                            "Visitor metrics read failed: %s", metrics_error_category(error)
                        )
                response = app.make_response(
                    render_template(
                        "owner_metrics.html",
                        installations=installations,
                        usage=usage,
                        feedback=feedback,
                        visitor_metrics_enabled=bool(visitor_store),
                    )
                )
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.get("/api/rules")
    def rules():
        return jsonify(rules=audit_rules(), total_weight=100)

    @app.get("/api/demo")
    def demo_report():
        """Return a stable, synthetic report so first-time evaluation never needs GitHub."""
        paths = [
            ".github/CODEOWNERS",
            ".github/workflows/release.yml",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "LICENSE",
            "README.md",
            "SECURITY.md",
            "database/migrations/002_add_sessions.sql",
            "package-lock.json",
            "package.json",
            "src/api/client.ts",
            "src/auth/session.ts",
            "tests/auth/session.test.ts",
        ]
        changed = [
            ChangedFile("src/auth/session.ts", additions=48, deletions=7),
            ChangedFile("src/api/client.ts", additions=12, deletions=2),
            ChangedFile("database/migrations/002_add_sessions.sql", additions=31),
            ChangedFile(".github/workflows/release.yml", additions=6, deletions=1),
        ]
        audit = audit_tree(
            paths,
            changed,
            codeowners_content=(
                "/src/auth/ @example/security\n"
                "/src/api/ @example/platform\n"
                "/database/ @example/data\n"
                "/.github/ @example/release\n"
            ),
        )
        audit = replace(
            audit,
            review_delta=ReviewDelta(
                baseline_sha="demo-reviewed-commit",
                reviewed_at="2026-10-07T18:00:00Z",
                changed_paths=("src/api/client.ts", ".github/workflows/release.yml"),
                changed_path_count=2,
                new_signals=audit.risks[:1],
                resolved_signals=(),
                changed_lanes=(("src", 1), (".github", 1)),
            ),
        )
        audit_data = audit.to_dict()
        pull = {
            "number": 42,
            "title": "Add authenticated sessions",
            "html_url": "https://github.com/Kxrma47/qnode-repo-auditor/blob/main/docs/demo.md",
            "state": "open",
            "draft": False,
            "head_sha": "demo-head",
            "base_sha": "demo-base",
            "head_ref": "feature/sessions",
            "base_ref": "main",
            "changed_files": len(changed),
            "additions": sum(file.additions for file in changed),
            "deletions": sum(file.deletions for file in changed),
        }
        checks = {
            "available": True,
            "complete": True,
            "observed": [
                {
                    "name": "unit tests",
                    "state": "success",
                    "html_url": "",
                    "configured": False,
                }
            ],
            "not_observed": [],
        }
        history = [
            {"paths": ["src/auth/session.ts", "tests/auth/session.test.ts", "docs/auth.md"]},
            {"paths": ["src/auth/session.ts", "tests/auth/session.test.ts"]},
            {"paths": ["src/api/client.ts", "tests/api/client.test.ts", "openapi/api.yaml"]},
            {"paths": ["src/api/client.ts", "tests/api/client.test.ts"]},
        ]
        intelligence = build_review_intelligence(
            audit,
            changed,
            pull=pull,
            ci=checks,
            history=history,
            reviewer_load={
                "@example/security": 1,
                "@example/platform": 3,
                "@example/data": 2,
                "@example/release": 1,
            },
        )
        return jsonify(
            repository={
                "full_name": "QNode demonstration",
                "html_url": "https://github.com/Kxrma47/qnode-repo-auditor/blob/main/docs/demo.md",
                "description": (
                    "Synthetic path-only pull-request evidence; no GitHub request was made."
                ),
                "default_branch": "main",
                "visibility": "public",
                "language": "TypeScript",
                "updated_at": "2026-10-08T00:00:00Z",
            },
            ref="demo-head",
            scanned_paths=len(paths),
            cached=False,
            demo=True,
            audit=audit_data,
            pull_request=pull,
            ci_evidence=checks,
            review_handoff=review_handoff(pull, audit_data, checks),
            intelligence=intelligence,
        )

    @app.post("/api/policy-preview")
    def policy_preview():
        """Preview path-only contracts without a GitHub request or source upload."""
        if request.content_length is None or request.content_length > 65536:
            return jsonify(error="Preview body must be at most 64 KiB."), 413
        values = request.get_json(silent=True)
        if not isinstance(values, dict) or set(values) - {
            "policy",
            "changed_paths",
            "files_truncated",
        }:
            return jsonify(error="Provide a policy and changed_paths."), 400
        policy_data = values.get("policy")
        paths = values.get("changed_paths")
        truncated = values.get("files_truncated", False)
        if (
            not isinstance(policy_data, dict)
            or not isinstance(paths, list)
            or type(truncated) is not bool
        ):
            return jsonify(error="Invalid preview fields."), 400
        if len(paths) > MAX_PR_FILES or not all(
            isinstance(path, str)
            and 0 < len(path) <= 500
            and not path.startswith("/")
            and ".." not in path.split("/")
            and "\\" not in path
            and not any(char in path for char in "*?[]|`\r\n")
            and all(ord(char) >= 32 for char in path)
            for path in paths
        ):
            return jsonify(
                error="changed_paths must be at most 1,000 repository-relative paths."
            ), 400
        policy = parse_policy(json.dumps(policy_data))
        if policy.warning:
            return jsonify(error=policy.warning), 400
        evidence = evaluate_change_contracts(
            (ChangedFile(path) for path in paths), policy, files_truncated=truncated
        )
        return jsonify(change_contracts=[item.to_dict() for item in evidence])

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
        if requested_ref and not valid_ref(requested_ref):
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
            record_successful_scan(bool(requested_pull))
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
            checks = None
            if pull:
                try:
                    checks = client.check_runs(repository, pull["head_sha"], token)
                except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
                    LOGGER.warning("PR check listing unavailable")
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

        audit_data = audit.to_dict()
        response = {
            "repository": info,
            "ref": ref,
            "scanned_paths": len(snapshot.paths),
            "cached": False,
            "audit": audit_data,
        }
        if pull:
            response["pull_request"] = pull
            response["ci_evidence"] = ci_evidence(checks, audit_data["review_map"])
            response["review_handoff"] = review_handoff(pull, audit_data, response["ci_evidence"])
            history = []
            reviewer_load = None
            intelligence_token = token
            if not intelligence_token and app.config["GITHUB_INSTALLATION_ID"]:
                try:
                    intelligence_token = client.installation_token(
                        int(app.config["GITHUB_INSTALLATION_ID"])
                    )
                except (requests.RequestException, ValueError, KeyError, TypeError):
                    LOGGER.warning("Public scan installation token unavailable")
            if intelligence_token:
                try:
                    history = client.recent_commit_paths(repository, ref, intelligence_token)
                except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
                    LOGGER.warning("Public filename history unavailable")
                try:
                    reviewer_load = reviewer_load_snapshot(
                        client.open_pull_requests(repository, intelligence_token, limit=30)
                    )
                except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
                    LOGGER.warning("Public reviewer load snapshot unavailable")
            response["intelligence"] = build_review_intelligence(
                audit,
                changed_files,
                pull=pull,
                ci=response["ci_evidence"],
                history=history,
                reviewer_load=reviewer_load,
            )
        public_cache[cache_key] = (time.monotonic(), response)
        if len(public_cache) > 256:
            oldest = min(public_cache, key=lambda key: public_cache[key][0])
            public_cache.pop(oldest, None)
        record_successful_scan(bool(requested_pull))
        return jsonify(response)

    @app.get("/api/attention")
    def attention_queue():
        if not app.config["PUBLIC_AUDIT_ENABLED"]:
            abort(404)
        repository = request.args.get("repository", "").strip()
        if not REPOSITORY_PATTERN.fullmatch(repository):
            return jsonify(error="Use a repository in owner/name format."), 400
        cached = attention_cache.get(repository.lower())
        if cached and time.monotonic() - cached[0] < 60:
            return jsonify(cached[1] | {"cached": True})
        try:
            client = github_client()
            token = app.config["GITHUB_PUBLIC_TOKEN"]
            info = client.repository_info(repository, token)
            if info["visibility"] != "public":
                return jsonify(error="Repository not found or not public."), 404
            pulls = client.open_pull_requests(repository, token, limit=5)
            items = []
            for pull in pulls:
                review_available = True
                try:
                    review = client.latest_submitted_review(repository, pull["number"], token)
                except (requests.RequestException, ValueError, KeyError, TypeError):
                    review = None
                    review_available = False
                try:
                    checks = client.check_runs(repository, pull["head_sha"], token)
                except (requests.RequestException, ValueError, KeyError, TypeError):
                    checks = None
                items.append(
                    attention_item(pull, review, checks, review_available=review_available)
                )
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else 502
            if status == 404:
                return jsonify(error="Repository not found or not public."), 404
            if status in {403, 429}:
                return jsonify(error="GitHub API rate limit reached. Try again later."), 429
            return jsonify(error="GitHub could not load open pull requests."), 502
        except requests.RequestException:
            return jsonify(error="GitHub is temporarily unreachable."), 502
        result = dict(
            repository=info["full_name"],
            items=sorted(items, key=lambda item: item["priority"]),
            scope=(
                "Up to five recently updated open PRs; signals are not personal assignments "
                "or merge requirements."
            ),
            cached=False,
        )
        attention_cache[repository.lower()] = (time.monotonic(), result)
        if len(attention_cache) > 128:
            attention_cache.pop(next(iter(attention_cache)))
        return jsonify(result)

    @app.get("/api/review-followup")
    def review_followup():
        if not app.config["PUBLIC_AUDIT_ENABLED"]:
            abort(404)
        repository = request.args.get("repository", "").strip()
        requested_pull = request.args.get("pull", "").strip()
        if not REPOSITORY_PATTERN.fullmatch(repository) or not PULL_PATTERN.fullmatch(
            requested_pull
        ):
            return jsonify(error="Provide a public repository and pull request number."), 400
        number = int(requested_pull)
        cache_key = (repository.lower(), number)
        cached = followup_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 60:
            return jsonify(cached[1] | {"cached": True})
        try:
            client = github_client()
            info = client.repository_info(repository, "")
            if info["visibility"] != "public":
                return jsonify(error="Repository or pull request not found or not public."), 404
            token = app.config["GITHUB_PUBLIC_TOKEN"]
            if not token and app.config["GITHUB_INSTALLATION_ID"]:
                token = client.installation_token(int(app.config["GITHUB_INSTALLATION_ID"]))
            if not token:
                return jsonify(error="Review follow-up needs GitHub API authentication."), 503
            snapshot = client.review_threads(info["full_name"], number, token)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else 502
            if status == 404:
                return jsonify(error="Repository or pull request not found or not public."), 404
            if status in {403, 429}:
                return jsonify(error="GitHub API rate limit reached. Try again later."), 429
            return jsonify(error="GitHub could not load review threads."), 502
        except LookupError:
            return jsonify(error="Repository or pull request not found or not public."), 404
        except (requests.RequestException, ValueError, KeyError, TypeError):
            return jsonify(error="Review thread evidence is temporarily unavailable."), 502
        unresolved = [thread for thread in snapshot["threads"] if not thread["resolved"]]
        result = {
            "repository": info["full_name"],
            "pull": number,
            "complete": snapshot["complete"],
            "total": snapshot["total"],
            "observed_unresolved": len(unresolved),
            "observed_resolved": len(snapshot["threads"]) - len(unresolved),
            "threads": sorted(
                unresolved, key=lambda thread: (not thread["outdated"], thread["path"])
            )[:50],
            "cached": False,
            "note": "Read-only review-thread metadata; outdated does not mean addressed.",
        }
        followup_cache[cache_key] = (time.monotonic(), result)
        if len(followup_cache) > 128:
            followup_cache.pop(next(iter(followup_cache)))
        return jsonify(result)

    @app.get("/api/compare")
    def compare_refs():
        if not app.config["PUBLIC_AUDIT_ENABLED"]:
            abort(404)
        repository = request.args.get("repository", "").strip()
        base_ref = request.args.get("base", "").strip()
        head_ref = request.args.get("head", "").strip()
        if not REPOSITORY_PATTERN.fullmatch(repository):
            return jsonify(error="Use a repository in owner/name format."), 400
        if not valid_ref(base_ref) or not valid_ref(head_ref):
            return jsonify(error="Provide valid base and head Git refs."), 400
        cache_key = (repository.lower(), base_ref, head_ref)
        cached = comparison_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < app.config["AUDIT_CACHE_SECONDS"]:
            return jsonify(cached[1] | {"cached": True})
        try:
            client = github_client()
            token = app.config["GITHUB_PUBLIC_TOKEN"]
            info = client.repository_info(repository, token)
            if info["visibility"] != "public":
                return jsonify(error="Repository or ref not found, or it is not public."), 404
            audits = []
            for ref in (base_ref, head_ref):
                snapshot = client.tree_snapshot(repository, ref, token)
                if snapshot.truncated:
                    return jsonify(
                        error="GitHub truncated a tree; a reliable comparison is unavailable."
                    ), 422
                codeowners_path = find_codeowners_path(snapshot.paths)
                codeowners_content = (
                    client.file_text(repository, codeowners_path, ref, token)
                    if codeowners_path
                    else ""
                )
                policy = repository_policy(client, repository, ref, token, snapshot.paths)
                audits.append(
                    audit_tree(snapshot.paths, codeowners_content=codeowners_content, policy=policy)
                )
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else 502
            if status == 404:
                return jsonify(error="Repository or ref not found, or it is not public."), 404
            if status in {403, 429}:
                return jsonify(error="GitHub API rate limit reached. Try again later."), 429
            return jsonify(error="GitHub could not compare these refs."), 502
        except requests.RequestException:
            return jsonify(error="GitHub is temporarily unreachable."), 502
        result = dict(
            repository=info["full_name"],
            comparison=compare_audits(audits[0], audits[1], base_ref, head_ref),
            cached=False,
        )
        comparison_cache[cache_key] = (time.monotonic(), result)
        if len(comparison_cache) > 128:
            comparison_cache.pop(next(iter(comparison_cache)))
        return jsonify(result)

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
