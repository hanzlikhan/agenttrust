"""Canonical argument serialization, hashing, and redaction (M04).

Hashing uses stable JSON: sorted keys, compact separators, ASCII output, and a
defined numeric representation (integers stay integers; floats are rejected at
the tool-schema validation layer, never silently normalized).
"""

import hashlib
import json
from typing import Any

MAX_ARGS_BYTES = 65536  # hard cap on the canonical argument payload

# Per-tool field allowlists for stored/redacted arguments. Unknown tools keep
# nothing: fail closed on redaction too. These fields are synthetic demo data;
# real tools must declare their own redaction config at registration.
_REDACT_ALLOWLIST: dict[str, set[str]] = {
    "refund_payment": {"order_id", "amount_minor", "currency"},
}


def canonical_json(value: Any) -> str:
    """Serialize to a canonical JSON string with stable property order."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def args_hash(args: dict[str, Any]) -> str:
    """SHA-256 hex digest of the canonical argument form.

    The same logical arguments always hash identically regardless of key order;
    any change to a value changes the hash.
    """
    return hashlib.sha256(canonical_json(args).encode("utf-8")).hexdigest()


def redact_args(tool_slug: str, args: dict[str, Any]) -> dict[str, Any]:
    """Return the allowlisted subset of arguments safe to persist.

    Unknown tools redact to an empty object rather than storing caller data.
    """
    allowed = _REDACT_ALLOWLIST.get(tool_slug)
    if allowed is None:
        return {}
    return {key: value for key, value in args.items() if key in allowed}


def contains_float(value: Any) -> bool:
    """True if any float appears anywhere in the structure.

    Floats are rejected for money: amounts must be integer minor units.
    Booleans are not floats (bool is a subclass of int, but never a float).
    """
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(contains_float(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_float(v) for v in value)
    return False
