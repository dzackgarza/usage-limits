"""Tests for the Agy Secret Pool provider and gemini-cli retirement.

The Antigravity CLI (daily channel) enforces quota against daily-cloudcode-pa.
The same credentials also resolve a SEPARATE, independently-metered Gemini pool
on production cloudcode-pa — proven independent (consuming one never moves the
other) and usable for live inference even while the agy-enforced pool is
exhausted. agy itself never touches it. This provider surfaces that spare pool.
"""

from __future__ import annotations

import json
from pathlib import Path

from usage_limits.base import ProviderAccount
from usage_limits.providers.agy_secret import AgySecretPoolAccount
from usage_limits.providers.antigravity import AntigravityAccount
from usage_limits.registry import FIRST_PARTY_PROVIDERS

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_agy_secret_registered_and_gemini_cli_retired() -> None:
    """agy-secret-pool is a first-party provider; gemini-cli is gone (moved to agy)."""
    assert "agy-secret-pool" in FIRST_PARTY_PROVIDERS
    assert FIRST_PARTY_PROVIDERS["agy-secret-pool"] is AgySecretPoolAccount
    assert "gemini-cli" not in FIRST_PARTY_PROVIDERS


def test_agy_secret_targets_production_host() -> None:
    """The secret pool queries production cloudcode-pa, not agy's daily host."""
    secret = AgySecretPoolAccount(account_id="test@example.com")
    anti = AntigravityAccount(account_id="test@example.com")
    assert secret._base_url() == "https://cloudcode-pa.googleapis.com"
    assert secret._base_url() != anti._base_url()


def test_agy_secret_reuses_pooled_parsing_with_own_label() -> None:
    """Inherits Antigravity's bucket parsing but labels availability as its own pool."""
    secret = AgySecretPoolAccount(account_id="test@example.com")
    raw = json.loads((FIXTURE_DIR / "antigravity-quota-summary-pooled.json").read_text())
    rows = secret.to_rows(raw)
    by_id = {r.identifier: r for r in rows}
    assert "Gemini Models (Weekly)" in by_id

    names = {a.name for a in secret.availability(rows)}
    assert "Agy Secret Pool: Gemini" in names
    assert not any(n.startswith("Antigravity:") for n in names)


def test_agy_secret_resolves_antigravity_accounts() -> None:
    """Reuses the antigravity credential store (no separate login)."""
    accounts = AgySecretPoolAccount.resolve_accounts()
    assert len(accounts) >= 1
    for acc in accounts:
        assert isinstance(acc, AgySecretPoolAccount)
        assert isinstance(acc, ProviderAccount)
        assert "@" in acc.account_id


def test_agy_secret_fetch_raw_returns_data() -> None:
    """Live API test: fetch_raw hits the production host and returns quota groups."""
    accounts = AgySecretPoolAccount.resolve_accounts()
    provider = accounts[0]
    raw = provider.fetch_raw()
    assert "groups" in raw
    assert len(raw["groups"]) >= 1
    rows = provider.to_rows(raw)
    assert len(rows) >= 1
    for row in rows:
        assert 0 <= row.pct_used <= 100
