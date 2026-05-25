"""Provider normalization tests for Antigravity.

Uses captured real API responses to exercise the
``fetch_raw`` → ``to_rows`` pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from usage_limits.providers.antigravity import AntigravityAccount

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_antigravity_to_rows_single_account() -> None:
    """to_rows produces rows with model-label identifiers for a single-account fixture."""
    provider = AntigravityAccount(account_id="test@example.com")
    raw = json.loads((FIXTURE_DIR / "antigravity-quota.json").read_text())
    rows = provider.to_rows(raw)

    assert len(rows) == 7

    # Identifiers are model labels (no email prefix — account is on snapshot)
    for row in rows:
        assert not row.identifier.startswith("Antigravity")
        assert row.identifier != ""

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

    # Verify identifiers include model labels only
    identifiers = [r.identifier for r in rows]
    assert "Claude Sonnet 4.6 (Thinking)" in identifiers
    assert "Gemini 3.5 Flash (High)" in identifiers


def test_antigravity_to_rows_with_fixture_account() -> None:
    """to_rows with a per-account fixture produces correct model data."""
    provider = AntigravityAccount(account_id="alpha@example.com")
    raw = json.loads((FIXTURE_DIR / "antigravity-quota-multi.json").read_text())

    # Filter to this account's models only (as fetch_raw would)
    account_models = [m for m in raw["models"] if m["accountEmail"] == "alpha@example.com"]
    account_raw = {"models": account_models}
    rows = provider.to_rows(account_raw)

    assert len(rows) == 7

    # Alpha account: Gemini are 40%, others are 100%
    for row in rows:
        if "Gemini" in row.identifier:
            assert row.pct_used == 40.0
        else:
            assert row.pct_used == 100.0


def test_antigravity_fetch_raw_returns_data() -> None:
    """Live API test: fetch_raw must return real quota data, not raise.
    Skips when no Antigravity credentials are available.
    """
    try:
        accounts = AntigravityAccount.resolve_accounts()
    except (FileNotFoundError, KeyError):
        pytest.skip("No Antigravity credentials available")
    assert len(accounts) >= 1
    provider = accounts[0]
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
        assert model.get("accountEmail") == provider.account_id

    # Parse the raw data through to_rows and verify output
    rows = provider.to_rows(raw)
    assert len(rows) >= 1

    for row in rows:
        # Identifiers are model labels only (no email prefix)
        assert not row.identifier.startswith("Antigravity")
        assert 0.0 <= row.pct_used <= 100.0


def test_antigravity_has_resolve_accounts_classmethod() -> None:
    """AntigravityAccount must expose a resolve_accounts classmethod."""
    assert hasattr(AntigravityAccount, "resolve_accounts")
    assert callable(AntigravityAccount.resolve_accounts)
