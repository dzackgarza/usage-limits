"""Provider normalization tests for OpenCode."""

from __future__ import annotations

from pathlib import Path

from usage_limits.providers.opencode import OpenCodeProvider

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_opencode_to_rows_extracts_go_usage_windows() -> None:
    provider = OpenCodeProvider()
    html = (FIXTURE_DIR / "opencode-go.html").read_text()
    rows = provider.to_rows({"html": html})

    assert len(rows) == 3

    five_hour = next(r for r in rows if "5h" in r.identifier)
    assert five_hour.pct_used == 0.0
    assert five_hour.reset_at is not None

    seven_day = next(r for r in rows if "7d" in r.identifier)
    assert seven_day.pct_used == 0.0
    assert seven_day.reset_at is not None

    thirty_day = next(r for r in rows if "30d" in r.identifier)
    assert thirty_day.pct_used == 100.0
    assert thirty_day.is_exhausted is True
    assert thirty_day.reset_at is not None
