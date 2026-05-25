"""Provider normalization test for Windsurf.

Exercises the fetch_raw -> to_rows pipeline against the live API.
The Windsurf provider reads an API key from SQLite state.vscdb,
calls the GetUserStatus endpoint, and parses daily/weekly quotas.
"""

from __future__ import annotations

from usage_limits.providers.windsurf import WindsurfProvider


def test_windsurf_live_api() -> None:
    """Windsurf fetch_raw + to_rows against live API must produce daily + weekly rows."""
    provider = WindsurfProvider()
    raw = provider.fetch_raw()
    rows = provider.to_rows(raw)

    assert len(rows) == 2

    # 24h row should have reset_at set
    h24 = [r for r in rows if "24h" in r.identifier]
    assert len(h24) == 1
    assert h24[0].reset_at is not None
    assert h24[0].pct_used >= 0

    # 7d row should have reset_at set
    w7 = [r for r in rows if "7d" in r.identifier]
    assert len(w7) == 1
    assert w7[0].reset_at is not None
    assert w7[0].pct_used >= 0
