import hashlib
import hmac

from qnode_auditor.app import create_app


def signed(secret: str, payload: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_health():
    client = create_app({"TESTING": True}).test_client()
    assert client.get("/health").json["status"] == "ready"


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
