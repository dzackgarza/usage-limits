"""Caching and TTL behavior tests for UsageProvider.

These prove:
1. Default TTL=0: every call re-fetches (different ``last_updated``)
2. Claude TTL=300: within-TTL calls return cached data (same ``last_updated``)
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
    """Claude (TTL=300) must return the same ``last_updated`` on rapid re-read.

    The second call reads from cache instead of hitting the API.  Without
    caching, each call would produce a different ``last_updated``.
    """
    first = collect_provider("claude")
    second = collect_provider("claude")

    assert first.metadata["last_updated"] == second.metadata["last_updated"]
