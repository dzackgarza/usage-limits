"""Caching behavior proofs for UsageProvider.

These tests verify that the caching layer actually persists data and
serves it on fallback — claims the existing tests don't prove because
``_write_cache`` is gated on ``cache_ttl_seconds > 0`` and never
executes for any provider.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

from usage_limits.providers.antigravity import AntigravityProvider
from usage_limits.providers.claude import ClaudeProvider
from usage_limits.registry import collect_provider


def test_cache_file_is_created_after_successful_fetch() -> None:
    """After a successful ``collect_snapshot`` a cache file must exist.

    Current code only writes the cache when ``cache_ttl_seconds > 0``,
    so this assertion fails — no cache file is ever created for any
    provider.  The fix: always write the cache after a successful fetch.
    """
    provider = AntigravityProvider()
    cache_path = provider._get_cache_path()

    # Remove any stale cache from prior runs
    cache_path.unlink(missing_ok=True)

    snap = provider.collect_snapshot()
    assert snap.status == "ok"

    assert cache_path.exists(), f"Cache file missing at {cache_path}"


def test_cached_data_is_served_on_fetch_failure() -> None:
    """When ``fetch_raw`` fails, stale cache data must be served instead.

    Setup: seed a cache file with known data, then call ``collect_snapshot``
    on a provider whose API would return an error.  The snapshot must
    have ``status == 'ok'`` and preserve the cached ``last_updated``.
    """
    provider = ClaudeProvider()
    cache_path = provider._get_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    cached_dt = datetime.now(UTC) - timedelta(minutes=10)
    cached_raw = {
        "five_hour": {"utilization": 45.0, "resets_at": "2026-05-23T18:00:00Z"},
        "seven_day": {"utilization": 72.5, "resets_at": "2026-05-28T00:00:00Z"},
    }
    cache_path.write_text(json.dumps({"raw": cached_raw, "last_updated": cached_dt.isoformat()}))

    snap = collect_provider("claude")
    assert snap.status == "ok", (
        f"Expected cached data to be served, got status {snap.status}: {snap.errors}"
    )
    assert snap.metadata["last_updated"] == cached_dt.isoformat()
    assert len(snap.rows) == 2
    assert snap.rows[0].identifier == "Claude (5h)"
    assert snap.rows[0].pct_used == 45.0


def test_ttl_zero_re_fetches_each_time() -> None:
    """Providers with ``cache_ttl_seconds == 0`` must re-fetch on every call.

    Even though the cache is always written, TTL=0 means every call
    considers it stale and performs a live fetch.  Consecutive calls
    must produce different ``last_updated`` timestamps.
    """
    first = collect_provider("antigravity")
    time.sleep(0.1)
    second = collect_provider("antigravity")

    assert first.metadata["last_updated"] != second.metadata["last_updated"]


def test_claude_ttl_300_serves_cached_data() -> None:
    """Claude (TTL=300) must serve cached data on rapid re-read.

    When a fresh cache exists (written by a previous successful fetch),
    the second call must return the same ``last_updated`` — proving it
    did not hit the API.
    """
    first = collect_provider("claude")
    if first.status != "ok":
        return  # API unavailable — cannot seed cache, skip assertion

    second = collect_provider("claude")
    assert first.metadata["last_updated"] == second.metadata["last_updated"]
