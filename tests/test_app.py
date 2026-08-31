import hashlib
import hmac
import json

from qnode_auditor.app import create_app
from qnode_auditor.audit import ChangedFile
from qnode_auditor.github import TreeSnapshot


def signed(secret: str, payload: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def webhook_headers(secret: str, payload: bytes, event: str, delivery: str = "delivery-1"):
    return {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": signed(secret, payload),
    }


def test_health_exposes_operational_capabilities_not_secrets():
    client = create_app(
        {"TESTING": True, "GITHUB_WEBHOOK_SECRET": "super-secret-value"}
    ).test_client()
    response = client.get("/health")
    assert response.json == {
        "public_audit": True,
        "service": "qnode-repo-auditor",
        "status": "ready",
        "version": "0.2.0",
        "webhook_configured": True,
    }
    assert "super-secret-value" not in response.text


def test_index_is_an_interactive_scanner_with_security_headers():
    client = create_app({"TESTING": True}).test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"Audit a GitHub repository" in response.data
    assert b"Kxrma47/qnode-repo-auditor" in response.data
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_rules_endpoint_describes_weighted_contract():
    client = create_app({"TESTING": True}).test_client()
    response = client.get("/api/rules")
    assert response.status_code == 200
    assert response.json["total_weight"] == 100
    assert len(response.json["rules"]) == 12


def test_ping_requires_and_accepts_signature():
    secret, payload = "test-secret", b'{"zen":"hello"}'
    client = create_app({"TESTING": True, "GITHUB_WEBHOOK_SECRET": secret}).test_client()
    assert client.post("/webhook", data=payload).status_code == 401
    response = client.post(
        "/webhook",
        data=payload,
        headers=webhook_headers(secret, payload, "ping"),
    )
    assert response.status_code == 200
    assert response.json["ok"] is True


def test_non_pull_request_event_is_ignored():
    secret, payload = "test-secret", b'{"action":"created"}'
    client = create_app({"TESTING": True, "GITHUB_WEBHOOK_SECRET": secret}).test_client()
    response = client.post(
        "/webhook",
        data=payload,
        headers=webhook_headers(secret, payload, "issues"),
    )
    assert response.status_code == 200
    assert response.json == {"ignored": True, "ok": True}


def test_pull_request_webhook_publishes_path_and_change_analysis(monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def installation_token(self, installation_id):
            calls["installation_id"] = installation_id
            return "token"

        def tree_snapshot(self, repository, sha, token):
            calls["tree"] = (repository, sha)
            return TreeSnapshot(["README.md", "src/app.py", "pyproject.toml"])

        def pull_request_files(self, repository, number, token):
            calls["pull_number"] = number
            return [
                ChangedFile("src/app.py", additions=30),
                ChangedFile("pyproject.toml", additions=2),
            ]

        def publish_check(self, repository, sha, audit, token):
            calls["score"] = audit.score
            calls["risks"] = [risk.key for risk in audit.risks]
            return {}

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    secret = "test-secret"
    payload = json.dumps(
        {
            "action": "opened",
            "number": 7,
            "repository": {"full_name": "Kxrma47/qnode-repo-auditor"},
            "pull_request": {"number": 7, "head": {"sha": "abc123"}},
        }
    ).encode()
    client = create_app(
        {
            "TESTING": True,
            "GITHUB_WEBHOOK_SECRET": secret,
            "GITHUB_INSTALLATION_ID": "157859600",
        }
    ).test_client()

    response = client.post(
        "/webhook",
        data=payload,
        headers=webhook_headers(secret, payload, "pull_request"),
    )

    assert response.status_code == 200
    assert response.json["risks"] == 2
    assert calls == {
        "installation_id": 157859600,
        "tree": ("Kxrma47/qnode-repo-auditor", "abc123"),
        "pull_number": 7,
        "score": 20,
        "risks": ["source-without-tests", "manifest-without-lock"],
    }


def test_duplicate_delivery_does_not_publish_twice(monkeypatch):
    published = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def installation_token(self, installation_id):
            return "token"

        def tree_snapshot(self, repository, sha, token):
            return TreeSnapshot(["README.md"])

        def pull_request_files(self, repository, number, token):
            return []

        def publish_check(self, repository, sha, audit, token):
            published.append(sha)
            return {}

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    secret = "secret"
    payload = json.dumps(
        {
            "action": "opened",
            "number": 1,
            "installation": {"id": 42},
            "repository": {"full_name": "owner/repo"},
            "pull_request": {"number": 1, "head": {"sha": "sha"}},
        }
    ).encode()
    app = create_app({"TESTING": True, "GITHUB_WEBHOOK_SECRET": secret})
    client = app.test_client()
    headers = webhook_headers(secret, payload, "pull_request", "same-delivery")
    assert client.post("/webhook", data=payload, headers=headers).status_code == 200
    second = client.post("/webhook", data=payload, headers=headers)
    assert second.json == {"duplicate": True, "ok": True}
    assert published == ["sha"]


def test_requested_check_action_reruns_pull_request_audit(monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def installation_token(self, installation_id):
            return "token"

        def tree_snapshot(self, repository, sha, token):
            calls["sha"] = sha
            return TreeSnapshot(["README.md"])

        def pull_request_files(self, repository, number, token):
            calls["number"] = number
            return []

        def publish_check(self, repository, sha, audit, token):
            calls["published"] = repository
            return {}

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    secret = "secret"
    payload = json.dumps(
        {
            "action": "requested_action",
            "requested_action": {"identifier": "rerun"},
            "installation": {"id": 42},
            "repository": {"full_name": "owner/repo"},
            "check_run": {"head_sha": "new-sha", "pull_requests": [{"number": 9}]},
        }
    ).encode()
    client = create_app({"TESTING": True, "GITHUB_WEBHOOK_SECRET": secret}).test_client()
    response = client.post(
        "/webhook",
        data=payload,
        headers=webhook_headers(secret, payload, "check_run", "rerun-delivery"),
    )
    assert response.status_code == 200
    assert calls == {"sha": "new-sha", "number": 9, "published": "owner/repo"}


def test_public_audit_fetches_repository_and_uses_cache(monkeypatch):
    calls = {"info": 0, "tree": 0}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def repository_info(self, repository, token=""):
            calls["info"] += 1
            return {
                "full_name": repository,
                "html_url": f"https://github.com/{repository}",
                "description": "Useful repository",
                "default_branch": "main",
                "visibility": "public",
                "language": "Python",
                "stars": 3,
                "forks": 1,
                "open_issues": 0,
                "archived": False,
                "updated_at": "2026-01-01T00:00:00Z",
            }

        def tree_snapshot(self, repository, ref, token=""):
            calls["tree"] += 1
            return TreeSnapshot(["README.md", "LICENSE", "tests/test.py"])

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    client = create_app({"TESTING": True}).test_client()
    first = client.get("/api/audit?repository=owner/repo")
    second = client.get("/api/audit?repository=owner/repo")
    assert first.status_code == 200
    assert first.json["cached"] is False
    assert first.json["audit"]["score"] == 36
    assert second.json["cached"] is True
    assert calls == {"info": 1, "tree": 1}


def test_public_audit_rejects_invalid_repository_and_ref():
    client = create_app({"TESTING": True}).test_client()
    assert client.get("/api/audit?repository=not-a-repository").status_code == 400
    assert client.get("/api/audit?repository=owner/repo&ref=../../secret").status_code == 400
