"""Small shared utilities."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)
