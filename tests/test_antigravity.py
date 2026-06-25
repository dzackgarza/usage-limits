"""Provider normalization tests for Antigravity.

Uses captured real ``retrieveUserQuotaSummary`` responses to exercise the
``fetch_raw`` -> ``to_rows`` -> ``availability`` pipeline.

The authoritative source is the enforced *individual* quota
(``retrieveUserQuotaSummary``), not ``fetchAvailableModels`` (which reports
every model as fully available even when the account is rate-limited).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from usage_limits.base import ProviderAccount
from usage_limits.providers.antigravity import AntigravityAccount
from usage_limits.registry import collect_all

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_antigravity_pooled_surfaces_exhausted_weekly_pool() -> None:
    """Real pooled-quota response: an exhausted weekly pool renders as 100% used.

    Regression: the provider previously read ``fetchAvailableModels``, which
    reported every model as available (``remainingPercentage: 1``) even while the
    account's enforced individual quota was exhausted — so the dashboard showed
    "100% available" while the CLI returned "Individual quota reached".
    """
    provider = AntigravityAccount(account_id="test@example.com")
    raw = json.loads((FIXTURE_DIR / "antigravity-quota-summary-pooled.json").read_text())
    rows = provider.to_rows(raw)
    by_id = {r.identifier: r for r in rows}

    # Pooled plan -> one row per (pool, window).
    assert set(by_id) == {
        "Gemini Models (Weekly)",
        "Gemini Models (5h)",
        "Claude and GPT models (Weekly)",
        "Claude and GPT models (5h)",
    }

    # Gemini pool fully available.
    assert by_id["Gemini Models (Weekly)"].pct_used == 0
    assert by_id["Gemini Models (5h)"].pct_used == 0

    # Claude/GPT weekly pool exhausted (remainingFraction 0).
    claude_weekly = by_id["Claude and GPT models (Weekly)"]
    assert claude_weekly.pct_used == 100
    assert claude_weekly.is_exhausted is True
    assert claude_weekly.reset_at == datetime(2026, 6, 28, 23, 55, 58, tzinfo=UTC)

    # The disabled 5h window inherits the binding (weekly) limit, not its own
    # raw remainingFraction (0.108) — the group is blocked until the weekly reset.
    claude_5h = by_id["Claude and GPT models (5h)"]
    assert claude_5h.pct_used == 100
    assert claude_5h.reset_at == datetime(2026, 6, 28, 23, 55, 58, tzinfo=UTC)


def test_antigravity_permodel_shape() -> None:
    """Older per-model plans render one row per model label, all available here."""
    provider = AntigravityAccount(account_id="test@example.com")
    raw = json.loads((FIXTURE_DIR / "antigravity-quota-summary-permodel.json").read_text())
    rows = provider.to_rows(raw)
    ids = {r.identifier for r in rows}

    assert "Gemini 3.5 Flash (High)" in ids
    assert "Claude Sonnet 4.6 (Thinking)" in ids
    assert "GPT-OSS 120B (Medium)" in ids
    # Fixture has remainingFraction 1 across the board.
    assert all(r.pct_used == 0 for r in rows)


def test_antigravity_availability_reflects_exhausted_pool() -> None:
    """availability() marks the exhausted Claude/GPT family unavailable, Gemini available."""
    provider = AntigravityAccount(account_id="test@example.com")
    raw = json.loads((FIXTURE_DIR / "antigravity-quota-summary-pooled.json").read_text())
    rows = provider.to_rows(raw)
    avail = {a.name: a for a in provider.availability(rows)}

    assert avail["Antigravity: Gemini"].available_now is True
    assert avail["Antigravity: Claude/GPT"].available_now is False
    assert avail["Antigravity: Claude/GPT"].available_when == datetime(
        2026, 6, 28, 23, 55, 58, tzinfo=UTC
    )


def test_antigravity_fetch_raw_returns_data() -> None:
    """Live API test: fetch_raw must return the quota-summary groups, not raise."""
    accounts = AntigravityAccount.resolve_accounts()
    assert len(accounts) >= 1
    provider = accounts[0]
    raw = provider.fetch_raw()

    assert "groups" in raw
    assert len(raw["groups"]) >= 1
    for group in raw["groups"]:
        assert "buckets" in group
        for bucket in group["buckets"]:
            assert "remainingFraction" in bucket

    rows = provider.to_rows(raw)
    assert len(rows) >= 1
    for row in rows:
        assert not row.identifier.startswith("Antigravity")
        assert 0 <= row.pct_used <= 100


def test_antigravity_has_resolve_accounts_classmethod() -> None:
    """AntigravityAccount must expose a resolve_accounts classmethod."""
    assert hasattr(AntigravityAccount, "resolve_accounts")
    accounts = AntigravityAccount.resolve_accounts()
    assert len(accounts) >= 1
    for acc in accounts:
        assert isinstance(acc, ProviderAccount)
        assert acc.account_id != ""
        assert "@" in acc.account_id


def test_antigravity_produces_per_account_snapshots() -> None:
    """collect_all produces one snapshot per Antigravity account."""
    collection = collect_all(providers=["antigravity"])
    antigravity_snaps = [s for s in collection.providers if s.provider == "antigravity"]
    assert len(antigravity_snaps) >= 1
    for snap in antigravity_snaps:
        assert snap.account is not None
        assert "@" in snap.account
