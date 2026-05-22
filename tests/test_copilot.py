"""Provider normalization tests for GitHub Copilot.

Uses a captured real API response to exercise the
``fetch_raw`` → ``to_rows`` pipeline. The fixture was
captured from the GitHub Copilot internal user API.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from usage_limits.providers.copilot import CopilotProvider

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_copilot_to_rows_with_captured_fixture() -> None:
    provider = CopilotProvider()
    raw = json.loads((FIXTURE_DIR / "copilot-usage.json").read_text())
    rows = provider.to_rows(raw)

    assert len(rows) == 3

    # Chat row (unlimited)
    chat = rows[0]
    assert chat.identifier == "Copilot (Chat)"
    assert chat.pct_used == 0.0  # unlimited
    assert chat.reset_at == datetime(2026, 6, 22, 0, 0, tzinfo=UTC)

    # Completions row (unlimited)
    completions = rows[1]
    assert completions.identifier == "Copilot (Completions)"
    assert completions.pct_used == 0.0  # unlimited
    assert completions.reset_at == datetime(2026, 6, 22, 0, 0, tzinfo=UTC)

    # Premium interactions row (exhausted)
    premium = rows[2]
    assert premium.identifier == "Copilot (Premium Interactions)"
    assert premium.pct_used == 100.0  # 100 - 0
    assert premium.is_exhausted is True
    assert premium.reset_at == datetime(2026, 6, 22, 0, 0, tzinfo=UTC)
