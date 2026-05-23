"""Provider normalization tests for Antigravity.

Uses captured real API responses to exercise the
``fetch_raw`` → ``to_rows`` pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

from usage_limits.providers.antigravity import AntigravityProvider

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_antigravity_to_rows_single_account() -> None:
    """to_rows produces rows tagged with the account email from a single-account fixture."""
    provider = AntigravityProvider()
    raw = json.loads((FIXTURE_DIR / "antigravity-quota.json").read_text())
    rows = provider.to_rows(raw)

    assert len(rows) == 7

    # All rows belong to the test account
    for row in rows:
        assert row.identifier.startswith("Antigravity (test@example.com): ")

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

    # Verify identifiers include the account email and model label
    identifiers = [r.identifier for r in rows]
    assert "Antigravity (test@example.com): Claude Sonnet 4.6 (Thinking)" in identifiers
    assert "Antigravity (test@example.com): Gemini 3.5 Flash (High)" in identifiers


def test_antigravity_to_rows_multi_account() -> None:
    """to_rows correctly handles models from multiple accounts."""
    provider = AntigravityProvider()
    raw = json.loads((FIXTURE_DIR / "antigravity-quota-multi.json").read_text())
    rows = provider.to_rows(raw)

    # Two accounts x 7 models each = 14 rows
    assert len(rows) == 14

    # Check both accounts are represented
    acct_a = [r for r in rows if "alpha@example.com" in r.identifier]
    acct_b = [r for r in rows if "beta@example.com" in r.identifier]
    assert len(acct_a) == 7
    assert len(acct_b) == 7

    # Account A has 40% Gemini usage
    for row in acct_a:
        if "Gemini" in row.identifier:
            assert row.pct_used == 40.0
        else:
            assert row.pct_used == 100.0

    # Account B has 100% Claude usage
    for row in acct_b:
        if "Claude" in row.identifier or "GPT" in row.identifier:
            assert row.pct_used == 100.0


def test_antigravity_fetch_raw_returns_data() -> None:
    """Live API test: fetch_raw must return real quota data, not raise."""
    provider = AntigravityProvider()
    raw = provider.fetch_raw()

    # Must have models key with at least one model
    assert "models" in raw
    assert len(raw["models"]) >= 1

    # Each model must have required fields (including accountEmail)
    for model in raw["models"]:
        assert "label" in model
        assert "modelId" in model
        assert "isExhausted" in model
        assert "resetTime" in model
        assert "accountEmail" in model

    # Parse the raw data through to_rows and verify output
    rows = provider.to_rows(raw)
    assert len(rows) >= 1

    for row in rows:
        # Must have the "Antigravity (...): " prefix with email
        assert row.identifier.startswith("Antigravity (")
        assert "): " in row.identifier
        assert 0.0 <= row.pct_used <= 100.0
