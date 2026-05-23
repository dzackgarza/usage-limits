"""Provider normalization test for Kiro.

Exercises the fetch_raw -> to_rows pipeline. Kiro reads credentials from
~/.local/share/kiro-cli/data.sqlite3, refreshes the access token if needed,
and calls the AWS CodeWhisperer getUsageLimits API.
"""

from __future__ import annotations

from usage_limits.providers.kiro import KiroProvider


def test_kiro_live_api() -> None:
    """Kiro fetch_raw + to_rows against live API must produce valid rows."""
    provider = KiroProvider()
    raw = provider.fetch_raw()
    rows = provider.to_rows(raw)

    # Must have usageBreakdownList
    assert len(raw["usageBreakdownList"]) >= 1

    # Must produce at least one row
    assert len(rows) >= 1

    # Each row should have identifier, pct_used, is_exhausted
    for row in rows:
        assert row.identifier is not None
        assert row.pct_used >= 0
        assert isinstance(row.is_exhausted, bool)
