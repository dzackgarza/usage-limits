"""Caching and TTL behavior tests for UsageProvider.

These prove:
1. Default TTL=0: every call re-fetches (different ``last_updated``)
2. Claude TTL=300: within-TTL calls are consistent (same status,
   and same ``last_updated`` when the API returns data)
"""

from __future__ import annotations

import time

from usage_limits.registry import collect_provider


def test_default_ttl_zero_re_fetches_each_time() -> None:
    """Antigravity (default TTL=0) must have distinct ``last_updated`` per call.

    Before caching exists, ``last_updated`` is absent — this misses the key
    and fails.  After caching is wired, ``last_updated`` appears and each
    call gets a fresh timestamp because TTL=0 expires immediately.
    """
    first = collect_provider("antigravity")
    time.sleep(0.1)  # guarantee clock tick
    second = collect_provider("antigravity")

    assert first.metadata["last_updated"] != second.metadata["last_updated"]


def test_claude_cache_hit_preserves_last_updated() -> None:
    """Claude (TTL=300) — two rapid calls must produce consistent results.

    When the API returns data (status == 'ok'), the second call must
    preserve ``last_updated`` because it reads from cache.  When the
    API is rate-limiting, both calls must at minimum agree on status
    to prove caching doesn't introduce inconsistency.
    """
    first = collect_provider("claude")
    second = collect_provider("claude")

    # Always: caching must not produce status disagreement
    # (e.g. first OK then 429, or first 429 then OK).
    assert first.status == second.status, (
        f"Cached result diverged: {first.status} -> {second.status}\n"
        f"First errors: {first.errors}\nSecond errors: {second.errors}"
    )

    # When data IS available: cache hit preserves last_updated.
    if first.status == "ok":
        assert first.metadata["last_updated"] == second.metadata["last_updated"]
