"""Minimal in-memory token-bucket rate limiter (security hardening).

One bucket per API key, refilling at `per_minute` tokens per minute. This is
deliberately single-process: it bounds abuse against one API instance but
does not coordinate across processes. A distributed limiter (Redis, shared
table) is future work if multi-process deployment demands it — recorded in
DECISIONS.md.

Thread-safe via a single lock; buckets are lazily created and never evicted
(localhost scale; documented limitation).
"""

import threading
import time

from .config import settings

_lock = threading.Lock()
# bucket key -> (tokens_available, last_refill_monotonic)
_buckets: dict[str, tuple[float, float]] = {}


def check_rate_limit(bucket: str, per_minute: int | None = None) -> bool:
    """Consume one token for `bucket`. Returns False when the bucket is empty.

    Returns a boolean (rather than raising) so this module stays independent
    of the HTTP error layer; callers translate False into a 429.
    """
    limit = per_minute if per_minute is not None else settings.AGENTTRUST_RATE_LIMIT_PER_MINUTE
    if limit <= 0:
        return True  # rate limiting disabled by configuration
    now = time.monotonic()
    with _lock:
        tokens, last = _buckets.get(bucket, (float(limit), now))
        tokens = min(float(limit), tokens + (now - last) * (limit / 60.0))
        if tokens < 1.0:
            return False
        _buckets[bucket] = (tokens - 1.0, now)
        return True


def reset_buckets() -> None:
    """Clear all buckets. Test-only helper; never called in production code."""
    with _lock:
        _buckets.clear()
