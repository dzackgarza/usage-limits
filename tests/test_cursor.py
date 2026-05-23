"""Provider normalization test for Cursor.

Exercises the fetch_raw -> to_rows pipeline against the live API.
The Cursor provider reads an access token from SQLite state.vscdb,
calls the usage-summary endpoint, and parses aggregate usage data.

Note: Free/unlimited plans have limit=0, producing 0 rows.
This is correct behavior — no quotas to track.
"""

from __future__ import annotations

from usage_limits.providers.cursor import CursorProvider


def test_cursor_live_api() -> None:
    """Cursor fetch_raw + to_rows against live API must produce valid rows."""
    provider = CursorProvider()
    raw = provider.fetch_raw()
    rows = provider.to_rows(raw)

    # Response must have membershipType
    assert raw["membershipType"] is not None

    # individualUsage must have plan and onDemand
    assert "plan" in raw["individualUsage"]
    assert "onDemand" in raw["individualUsage"]

    # Must produce at least one row (plan usage always reported)
    assert len(rows) >= 1

    # Plan row should have valid fields
    plan_row = rows[0]
    assert plan_row.identifier is not None
    assert plan_row.pct_used >= 0
    assert isinstance(plan_row.is_exhausted, bool)
