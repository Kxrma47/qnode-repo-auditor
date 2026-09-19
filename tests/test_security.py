import hashlib
import hmac

import pytest

from qnode_auditor.app import create_app
from qnode_auditor.security import validate_secret_strength, verify_signature


def test_valid_signature():
    payload, secret = b'{"zen":"test"}', "quantum-secret"
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_signature(payload, f"sha256={digest}", secret)


def test_invalid_or_missing_signature():
    assert not verify_signature(b"payload", "sha256=bad", "secret")
    assert not verify_signature(b"payload", None, "secret")


@pytest.mark.parametrize("name", ["GITHUB_WEBHOOK_SECRET", "OWNER_METRICS_TOKEN"])
def test_production_rejects_short_authentication_secrets(monkeypatch, name):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("OWNER_METRICS_TOKEN", raising=False)
    with pytest.raises(ValueError, match=name):
        create_app({name: "short"})


def test_32_byte_secrets_pass_validation():
    validate_secret_strength("GITHUB_WEBHOOK_SECRET", "x" * 32)
    create_app({"GITHUB_WEBHOOK_SECRET": "x" * 32, "OWNER_METRICS_TOKEN": "y" * 32})
