"""Provider normalization tests for Freebuff.

Uses captured real API responses to exercise the fetch_raw → to_rows pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from usage_limits.providers.freebuff import FreebuffProvider

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "freebuff"


def test_freebuff_to_rows_active() -> None:
    provider = FreebuffProvider()
    session_raw = json.loads((FIXTURE_DIR / "session_active.json").read_text())
    usage_raw = json.loads((FIXTURE_DIR / "usage.json").read_text())

    raw = {"session": session_raw, "usage": usage_raw}
    rows = provider.to_rows(raw)

    assert len(rows) == 2

    # 1. Hourly Session Lease Limit
    lease = rows[0]
    assert lease.identifier == "Freebuff (Session Lease)"
    # remainingMs = 3312343 (approx 55 mins remaining out of 1 hour / 3600000 ms)
    # pct_used = 100 - round((3312343 / 3600000) * 100) = 100 - 92 = 8%
    assert lease.pct_used == 8
    assert lease.is_exhausted is False
    assert lease.reset_at == datetime(2026, 7, 7, 10, 11, 23, 977000, tzinfo=UTC)

    # 2. Daily Session Quota Limit (Limit is 5 sessions)
    quota = rows[1]
    assert quota.identifier == "Freebuff (Daily Quota)"
    # limit = 5, recentCount = 1 => 20%
    assert quota.pct_used == 20
    assert quota.is_exhausted is False
    assert quota.reset_at == datetime(2026, 7, 8, 7, 0, 0, tzinfo=UTC)


def test_freebuff_to_rows_none() -> None:
    provider = FreebuffProvider()
    session_raw = json.loads((FIXTURE_DIR / "session_none.json").read_text())
    usage_raw = json.loads((FIXTURE_DIR / "usage.json").read_text())

    raw = {"session": session_raw, "usage": usage_raw}
    rows = provider.to_rows(raw)

    assert len(rows) == 2

    # 1. Hourly Session Lease Limit
    lease = rows[0]
    assert lease.identifier == "Freebuff (Session Lease)"
    assert lease.pct_used == 0
    assert lease.is_exhausted is False
    assert lease.reset_at is None

    # 2. Daily Session Quota Limit
    quota = rows[1]
    assert quota.identifier == "Freebuff (Daily Quota)"
    assert quota.pct_used == 0
    assert quota.is_exhausted is False
    assert quota.reset_at is None


def test_freebuff_missing_credentials(tmp_path: Path) -> None:
    provider = FreebuffProvider()
    provider.cred_file = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError):
        provider.fetch_raw()
