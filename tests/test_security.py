import hashlib
import hmac

from qnode_auditor.security import verify_signature


def test_valid_signature():
    payload, secret = b'{"zen":"test"}', "quantum-secret"
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_signature(payload, f"sha256={digest}", secret)


def test_invalid_or_missing_signature():
    assert not verify_signature(b"payload", "sha256=bad", "secret")
    assert not verify_signature(b"payload", None, "secret")
