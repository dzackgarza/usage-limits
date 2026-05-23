"""Provider normalization tests for Antigravity.

Uses a captured real API response to exercise the
``fetch_raw`` → ``to_rows`` pipeline. The fixture was
captured from ``npx antigravity-usage quota --json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from usage_limits.providers.antigravity import AntigravityProvider

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_antigravity_to_rows_with_captured_fixture() -> None:
    provider = AntigravityProvider()
    raw = json.loads((FIXTURE_DIR / "antigravity-quota.json").read_text())
    rows = provider.to_rows(raw)

    assert len(rows) == 7

    # Models with remainingPercentage → calculated from (1 - remaining) * 100
    gemini = {r.identifier: r for r in rows if "Gemini" in r.identifier}
    assert len(gemini) == 4
    for g in gemini.values():
        assert g.pct_used == 40.0  # fixture has remainingPercentage=0.6
        assert g.is_exhausted is False
        assert g.reset_at is not None

    # Models without remainingPercentage (upstream tool bug) → 100% used
    exhausted = {r.identifier: r for r in rows if "Gemini" not in r.identifier}
    assert len(exhausted) == 3
    for e in exhausted.values():
        assert e.pct_used == 100.0
        assert e.is_exhausted is True
        assert e.reset_at is not None

    # Verify identifiers include the label from the API
    assert "Antigravity: Claude Sonnet 4.6 (Thinking)" in [r.identifier for r in rows]
    assert "Antigravity: Gemini 3.5 Flash (High)" in [r.identifier for r in rows]


def test_antigravity_fetch_raw_returns_data() -> None:
    """Live API test: fetch_raw must return real quota data, not raise."""
    provider = AntigravityProvider()
    raw = provider.fetch_raw()

    # Must have models key with at least one model
    assert "models" in raw
    assert len(raw["models"]) >= 1

    # Each model must have required fields
    for model in raw["models"]:
        assert "label" in model
        assert "modelId" in model
        assert "isExhausted" in model
        assert "resetTime" in model

    # Parse the raw data through to_rows and verify output
    rows = provider.to_rows(raw)
    assert len(rows) >= 1

    for row in rows:
        assert row.identifier.startswith("Antigravity: ")
        assert 0.0 <= row.pct_used <= 100.0
