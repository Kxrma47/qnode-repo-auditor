import os

from flask import Flask, abort, jsonify, render_template_string, request

from .audit import audit_tree
from .github import GitHubAppClient
from .security import verify_signature


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        GITHUB_APP_ID=os.getenv("GITHUB_APP_ID", ""),
        GITHUB_PRIVATE_KEY=os.getenv("GITHUB_PRIVATE_KEY", ""),
        GITHUB_PRIVATE_KEY_PATH=os.getenv("GITHUB_PRIVATE_KEY_PATH", ""),
        GITHUB_INSTALLATION_ID=os.getenv("GITHUB_INSTALLATION_ID", ""),
        GITHUB_WEBHOOK_SECRET=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
    )
    if config:
        app.config.update(config)

    @app.get("/")
    def index():
        return render_template_string(
            """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>QNode Repository Auditor</title>
  <style>
    :root { color-scheme: dark; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #071019; color: #c9d7e3; }
    main { width: min(680px, calc(100% - 32px)); padding: 32px; border: 1px solid #1c6070; background: #0a1621; box-shadow: 0 0 48px #00d9ff12; }
    p { line-height: 1.65; }
    .eyebrow { color: #61e7ff; font-size: .78rem; letter-spacing: .14em; }
    h1 { margin: 12px 0; color: #f1f7fb; font-size: clamp(1.55rem, 5vw, 2.3rem); }
    .status { display: inline-flex; gap: 8px; align-items: center; color: #73f7bd; }
    .status::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: currentColor; box-shadow: 0 0 12px currentColor; }
    nav { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }
    a { color: #7de8ff; text-decoration: none; border-bottom: 1px solid #2f7080; }
    a:hover { color: #fff; border-color: #fff; }
  </style>
</head>
<body>
  <main>
    <div class="eyebrow">QNODE // SERVICE STATUS</div>
    <h1>Repository Auditor</h1>
    <p>Signed pull-request webhooks, deterministic repository checks, and minimal GitHub permissions.</p>
    <div class="status">OPERATIONAL</div>
    <nav>
      <a href="/health">Health endpoint</a>
      <a href="https://github.com/Kxrma47/qnode-repo-auditor">Source repository</a>
    </nav>
  </main>
</body>
</html>"""
        )

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

        installation_id = (payload.get("installation") or {}).get("id")
        installation_id = installation_id or app.config["GITHUB_INSTALLATION_ID"]
        if not installation_id:
            abort(503)
        repository = payload["repository"]["full_name"]
        sha = payload["pull_request"]["head"]["sha"]
        client = GitHubAppClient(
            app_id=app.config["GITHUB_APP_ID"],
            private_key=app.config["GITHUB_PRIVATE_KEY"],
            private_key_path=app.config["GITHUB_PRIVATE_KEY_PATH"],
        )
        token = client.installation_token(int(installation_id))
        audit = audit_tree(client.tree_paths(repository, sha, token))
        client.publish_check(repository, sha, audit, token)
        return jsonify(ok=True, score=audit.score)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
