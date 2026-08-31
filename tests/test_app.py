import hashlib
import hmac

from qnode_auditor.app import create_app


def signed(secret: str, payload: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_health():
    client = create_app({"TESTING": True}).test_client()
    assert client.get("/health").json["status"] == "ready"


def test_index():
    client = create_app({"TESTING": True}).test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"QNode Repository Auditor" in response.data
    assert b"OPERATIONAL" in response.data


def test_ping_requires_and_accepts_signature():
    secret, payload = "test-secret", b'{"zen":"hello"}'
    client = create_app({"TESTING": True, "GITHUB_WEBHOOK_SECRET": secret}).test_client()
    assert client.post("/webhook", data=payload).status_code == 401
    response = client.post(
        "/webhook", data=payload,
        headers={"Content-Type": "application/json", "X-GitHub-Event": "ping", "X-Hub-Signature-256": signed(secret, payload)},
    )
    assert response.status_code == 200
    assert response.json["ok"] is True


def test_non_pull_request_event_is_ignored():
    secret, payload = "test-secret", b'{"action":"created"}'
    client = create_app({"TESTING": True, "GITHUB_WEBHOOK_SECRET": secret}).test_client()
    response = client.post(
        "/webhook", data=payload,
        headers={"Content-Type": "application/json", "X-GitHub-Event": "issues", "X-Hub-Signature-256": signed(secret, payload)},
    )
    assert response.status_code == 200
    assert response.json == {"ignored": True, "ok": True}


def test_repository_webhook_uses_configured_installation(monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def installation_token(self, installation_id):
            calls["installation_id"] = installation_id
            return "token"

        def tree_paths(self, repository, sha, token):
            return ["README.md", "LICENSE", "tests/test_app.py"]

        def publish_check(self, repository, sha, audit, token):
            calls["repository"] = repository

    monkeypatch.setattr("qnode_auditor.app.GitHubAppClient", FakeClient)
    secret = "test-secret"
    payload = (
        b'{"action":"opened","repository":{"full_name":"Kxrma47/qnode-repo-auditor"},'
        b'"pull_request":{"head":{"sha":"abc123"}}}'
    )
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
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": signed(secret, payload),
        },
    )

    assert response.status_code == 200
    assert calls == {
        "installation_id": 157859600,
        "repository": "Kxrma47/qnode-repo-auditor",
    }
