"""Provider normalization tests for Kiro.

Uses a captured real API response to exercise the
``fetch_raw`` → ``to_rows`` pipeline. The fixture was
captured from the Kiro runtime usage API.
"""

from __future__ import annotations

import json
from pathlib import Path

from usage_limits.providers.kiro import KiroProvider

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_kiro_to_rows_with_captured_fixture() -> None:
    provider = KiroProvider()
    raw = json.loads((FIXTURE_DIR / "kiro-usage.json").read_text())
    rows = provider.to_rows(raw)

    assert len(rows) == 1

    # Main credits row
    row = rows[0]
    assert row.identifier == "Kiro (Credit)"
    assert row.pct_used == 100.0  # 50/50 used
    assert row.is_exhausted is True
    assert row.reset_at is not None


def test_kiro_to_rows_with_active_bonus() -> None:
    provider = KiroProvider()
    raw = json.loads((FIXTURE_DIR / "kiro-usage.json").read_text())

    # Modify fixture to have active bonus
    raw["usageBreakdownList"][0]["freeTrialInfo"]["freeTrialStatus"] = "ACTIVE"
    raw["usageBreakdownList"][0]["freeTrialInfo"]["currentUsage"] = 250

    rows = provider.to_rows(raw)

    assert len(rows) == 2

    # Main credits row
    main = rows[0]
    assert main.identifier == "Kiro (Credit)"
    assert main.pct_used == 100.0  # 50/50 used
    assert main.is_exhausted is True

    # Bonus row
    bonus = rows[1]
    assert bonus.identifier == "Kiro Bonus (Credit)"
    assert bonus.pct_used == 50.0  # 250/500 used
    assert bonus.is_exhausted is False
