"""Provider normalization tests for Cursor.

Uses a captured API response shape to exercise the
``fetch_raw`` → ``to_rows`` pipeline. The fixture shape
matches the Cursor usage-summary API response.
"""

from __future__ import annotations

import json
from pathlib import Path

from usage_limits.providers.cursor import CursorProvider

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_cursor_to_rows_with_captured_fixture() -> None:
    provider = CursorProvider()
    raw = json.loads((FIXTURE_DIR / "cursor-usage.json").read_text())
    rows = provider.to_rows(raw)

    # 4 models with int maxRequestUsage (gpt35 has "No Limit" so excluded)
    assert len(rows) == 4

    # GPT-4 row: 125/500 = 25%
    gpt4 = rows[0]
    assert gpt4.identifier == "Cursor (pro - gpt4)"
    assert gpt4.pct_used == 25.0
    assert gpt4.is_exhausted is False
    assert gpt4.reset_at is None

    # Codex row: 10/100 = 10%
    codex = rows[1]
    assert codex.identifier == "Cursor (pro - codex)"
    assert codex.pct_used == 10.0

    # O1 row: 50/200 = 25%
    o1 = rows[2]
    assert o1.identifier == "Cursor (pro - o1)"
    assert o1.pct_used == 25.0

    # Sonnet row: 300/1000 = 30%
    sonnet = rows[3]
    assert sonnet.identifier == "Cursor (pro - sonnet)"
    assert sonnet.pct_used == 30.0
    assert sonnet.is_exhausted is False
