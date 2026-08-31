import os

from flask import Flask, abort, jsonify, request

from .audit import audit_tree
from .github import GitHubAppClient
from .security import verify_signature


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        GITHUB_APP_ID=os.getenv("GITHUB_APP_ID", ""),
        GITHUB_PRIVATE_KEY=os.getenv("GITHUB_PRIVATE_KEY", ""),
        GITHUB_PRIVATE_KEY_PATH=os.getenv("GITHUB_PRIVATE_KEY_PATH", ""),
        GITHUB_WEBHOOK_SECRET=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
    )
    if config:
        app.config.update(config)

    @app.get("/health")
    def health():
        return jsonify(status="ready", service="qnode-repo-auditor")

    @app.post("/webhook")
    def webhook():
        raw = request.get_data()
        if not verify_signature(
            raw,
            request.headers.get("X-Hub-Signature-256"),
            app.config["GITHUB_WEBHOOK_SECRET"],
        ):
            abort(401)

        event = request.headers.get("X-GitHub-Event")
        payload = request.get_json(silent=True) or {}
        if event == "ping":
            return jsonify(ok=True, message="QNode channel open")
        if event != "pull_request" or payload.get("action") not in {
            "opened", "reopened", "synchronize", "ready_for_review"
        }:
            return jsonify(ok=True, ignored=True)

        installation_id = payload["installation"]["id"]
        repository = payload["repository"]["full_name"]
        sha = payload["pull_request"]["head"]["sha"]
        client = GitHubAppClient(
            app_id=app.config["GITHUB_APP_ID"],
            private_key=app.config["GITHUB_PRIVATE_KEY"],
            private_key_path=app.config["GITHUB_PRIVATE_KEY_PATH"],
        )
        token = client.installation_token(installation_id)
        audit = audit_tree(client.tree_paths(repository, sha, token))
        client.publish_check(repository, sha, audit, token)
        return jsonify(ok=True, score=audit.score)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
