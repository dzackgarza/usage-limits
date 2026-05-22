"""Provider normalization tests for Windsurf.

Uses a captured real API response to exercise the
``fetch_raw`` → ``to_rows`` pipeline. The fixture was
captured from the Windsurf GetUserStatus API.
"""

from __future__ import annotations

import json
from pathlib import Path

from usage_limits.providers.windsurf import WindsurfProvider

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_windsurf_to_rows_with_captured_fixture() -> None:
    provider = WindsurfProvider()
    raw = json.loads((FIXTURE_DIR / "windsurf-usage.json").read_text())
    rows = provider.to_rows(raw)

    assert len(rows) == 2

    # Prompt credits row
    prompt = rows[0]
    assert prompt.identifier == "Windsurf (Pro - Prompt)"
    assert prompt.pct_used == 50.0  # 50/100 used
    assert prompt.is_exhausted is False
    assert prompt.reset_at is not None

    # Flow credits row
    flow = rows[1]
    assert flow.identifier == "Windsurf (Pro - Flow)"
    assert flow.pct_used == 50.0  # 100/200 used
    assert flow.is_exhausted is False
    assert flow.reset_at is not None
