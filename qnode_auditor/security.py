import hashlib
import hmac

MIN_SECRET_BYTES = 32


def validate_secret_strength(name: str, secret: str) -> None:
    """Enforce a minimum size for externally generated authentication secrets."""
    if secret and len(secret.encode("utf-8")) < MIN_SECRET_BYTES:
        raise ValueError(f"{name} must contain at least {MIN_SECRET_BYTES} UTF-8 bytes")


def verify_signature(payload: bytes, signature: str | None, secret: str) -> bool:
    """Verify a GitHub webhook's SHA-256 signature without timing leaks."""
    if not signature or not secret or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
