"""Caching behavior proofs for UsageProvider.

These tests verify that the caching layer actually persists data and
serves it on fallback — claims the existing tests don't prove because
``_write_cache`` is gated on ``cache_ttl_seconds > 0`` and never
executes for any provider.

All caching tests use fixture data (captured real API responses) or
AntigravityProvider (always succeeds, no rate limits).  No test depends
on a specific API returning success or failure at runtime.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests

from usage_limits.providers.antigravity import AntigravityProvider
from usage_limits.providers.claude import ClaudeProvider
from usage_limits.registry import collect_provider

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Core cache behaviour
# ---------------------------------------------------------------------------


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


def test_read_cache_returns_fresh_data() -> None:
    """``_read_cache`` returns data when it exists and is within TTL."""
    provider = ClaudeProvider()
    cache_path = provider._get_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    fixture = json.loads(FIXTURES.joinpath("claude_response.json").read_text())
    cached_dt = datetime.now(UTC) - timedelta(seconds=60)
    cache_path.write_text(json.dumps({"raw": fixture, "last_updated": cached_dt.isoformat()}))

    result = provider._read_cache()
    assert result is not None, "Expected fresh cache hit, got None"
    raw, ts = result
    assert ts == cached_dt
    assert raw["five_hour"]["utilization"] == 5.0


def test_read_cache_returns_none_on_stale() -> None:
    """``_read_cache`` returns None when data exists but is outside TTL."""
    provider = ClaudeProvider()
    cache_path = provider._get_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    fixture = json.loads(FIXTURES.joinpath("claude_response.json").read_text())
    cached_dt = datetime.now(UTC) - timedelta(minutes=10)
    cache_path.write_text(json.dumps({"raw": fixture, "last_updated": cached_dt.isoformat()}))

    result = provider._read_cache()
    assert result is None, "Expected stale cache to return None"


def test_read_cache_ignore_ttl_returns_stale() -> None:
    """``_read_cache(ignore_ttl=True)`` returns data even when outside TTL.

    This is the fallback path used when a live fetch fails — the stale
    cache data is served rather than propagating the error.
    """
    provider = ClaudeProvider()
    cache_path = provider._get_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    fixture = json.loads(FIXTURES.joinpath("claude_response.json").read_text())
    cached_dt = datetime.now(UTC) - timedelta(minutes=10)
    cache_path.write_text(json.dumps({"raw": fixture, "last_updated": cached_dt.isoformat()}))

    result = provider._read_cache(ignore_ttl=True)
    assert result is not None, "Expected stale cache to be returned with ignore_ttl=True"
    raw, ts = result
    assert ts == cached_dt


def test_fresh_cache_hit_within_ttl() -> None:
    """A cache entry younger than TTL must be served via ``collect_provider``.

    Seed a cache file with fixture data that is 60s old (well within
    the 300s TTL of ClaudeProvider).  The provider must return the
    cached rows without ever calling ``fetch_raw`` — proven by the
    ``last_updated`` matching the seeded timestamp.
    """
    provider = ClaudeProvider()
    cache_path = provider._get_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    fixture = json.loads(FIXTURES.joinpath("claude_response.json").read_text())
    cached_dt = datetime.now(UTC) - timedelta(seconds=60)
    cache_path.write_text(json.dumps({"raw": fixture, "last_updated": cached_dt.isoformat()}))

    snap = collect_provider("claude")
    assert snap.status == "ok", f"Cache hit failed: {snap.errors}"
    assert snap.metadata["last_updated"] == cached_dt.isoformat()
    assert len(snap.rows) == 2
    assert snap.rows[0].identifier == "Claude (5h)"
    assert snap.rows[0].pct_used == 5.0


# ---------------------------------------------------------------------------
# Failure caching (option C): persist fetch failures so we do not retry
# within TTL, and raise from cache when a recent failure exists.
# ---------------------------------------------------------------------------


def test_write_cache_error_persists_error_type() -> None:
    """``_write_cache_error`` must write a cache entry with error metadata."""
    provider = ClaudeProvider()
    cache_path = provider._get_cache_path()
    cache_path.unlink(missing_ok=True)

    error = requests.HTTPError("test fetch failure")
    provider._write_cache_error(error)

    assert cache_path.exists(), f"No error cache written at {cache_path}"
    data = json.loads(cache_path.read_text())
    assert data["error_type"] == "HTTPError"
    assert data["error_message"] == "test fetch failure"


def test_write_cache_error_preserves_stale_data() -> None:
    """``_write_cache_error`` must not overwrite existing raw data.

    When a prior successful fetch left raw data in the cache, an
    error write should preserve it so stale fallback still works.
    """
    provider = ClaudeProvider()
    cache_path = provider._get_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    fixture = json.loads(FIXTURES.joinpath("claude_response.json").read_text())
    cached_dt = datetime.now(UTC) - timedelta(minutes=10)
    cache_path.write_text(json.dumps({"raw": fixture, "last_updated": cached_dt.isoformat()}))

    error = requests.HTTPError("test fetch failure")
    provider._write_cache_error(error)

    data = json.loads(cache_path.read_text())
    assert data["raw"] is not None, "raw data was wiped by error write"
    assert data["raw"]["five_hour"]["utilization"] == 5.0


def test_reject_cached_failure_raises_within_ttl() -> None:
    """``_reject_cached_failure`` must raise ``HTTPError`` when a cached
    error exists and is within TTL, preventing an unnecessary API call."""
    provider = ClaudeProvider()
    cache_path = provider._get_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    error_dt = datetime.now(UTC) - timedelta(seconds=60)
    cache_path.write_text(
        json.dumps(
            {
                "raw": None,
                "error_type": "HTTPError",
                "error_message": "cached failure",
                "last_updated": error_dt.isoformat(),
            }
        )
    )

    with pytest.raises(requests.HTTPError):
        provider._reject_cached_failure()


def test_reject_cached_failure_returns_on_ttl_expired() -> None:
    """``_reject_cached_failure`` must return normally when the cached
    error has exceeded TTL — the caller should retry ``fetch_raw``."""
    provider = ClaudeProvider()
    cache_path = provider._get_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    error_dt = datetime.now(UTC) - timedelta(minutes=10)
    cache_path.write_text(
        json.dumps(
            {
                "raw": None,
                "error_type": "HTTPError",
                "error_message": "stale cached failure",
                "last_updated": error_dt.isoformat(),
            }
        )
    )

    # Should not raise — the error is stale
    provider._reject_cached_failure()
