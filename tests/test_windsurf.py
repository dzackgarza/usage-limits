"""Provider normalization test for Windsurf.

Exercises the fetch_raw -> to_rows pipeline against the live API.
The Windsurf provider reads an API key from SQLite state.vscdb,
calls the GetUserStatus endpoint, and parses plan credits + quotas.
"""

from __future__ import annotations

from usage_limits.providers.windsurf import WindsurfProvider


def test_windsurf_live_api() -> None:
    """Windsurf fetch_raw + to_rows against live API must produce valid rows."""
    provider = WindsurfProvider()
    raw = provider.fetch_raw()
    rows = provider.to_rows(raw)

    # Must have at least prompt + flow credits rows
    assert len(rows) >= 2

    # First row should be prompt credits
    prompt = rows[0]
    assert "Prompt" in prompt.identifier
    assert prompt.pct_used >= 0
    assert prompt.is_exhausted is False

    # Second row should be flow credits
    flow = rows[1]
    assert "Flow" in flow.identifier
    assert flow.pct_used >= 0
    assert flow.is_exhausted is False

    # Daily and weekly quota rows should have reset_at set
    daily = [r for r in rows if "Daily" in r.identifier]
    assert len(daily) == 1
    assert daily[0].reset_at is not None
    assert daily[0].pct_used >= 0

    weekly = [r for r in rows if "Weekly" in r.identifier]
    assert len(weekly) == 1
    assert weekly[0].reset_at is not None
    assert weekly[0].pct_used >= 0
