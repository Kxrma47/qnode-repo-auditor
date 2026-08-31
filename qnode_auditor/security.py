import hashlib
import hmac


def verify_signature(payload: bytes, signature: str | None, secret: str) -> bool:
    """Verify a GitHub webhook's SHA-256 signature without timing leaks."""
    if not signature or not secret or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
