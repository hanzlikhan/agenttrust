"""API key generation and verification.

The raw secret is generated with a CSPRNG, shown to the caller exactly once,
and never persisted. Only a short lookup prefix and the SHA-256 hash are
stored in the database.
"""

import hashlib
import secrets

KEY_SCHEME_PREFIX = "at_"
KEY_RANDOM_BYTES = 32
KEY_PREFIX_CHARS = 12  # characters after "at_" kept for indexed lookup


def generate_api_key() -> tuple[str, str, str]:
    """Return ``(raw_key, key_prefix, key_hash)`` for a new API key."""
    raw = KEY_SCHEME_PREFIX + secrets.token_urlsafe(KEY_RANDOM_BYTES)
    prefix = raw[: len(KEY_SCHEME_PREFIX) + KEY_PREFIX_CHARS]
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, prefix, digest


def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    """Constant-time comparison of a presented key against the stored hash."""
    candidate = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return secrets.compare_digest(candidate, stored_hash)
