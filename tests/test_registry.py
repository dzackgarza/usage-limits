"""Registry tests for the canonical provider surface."""

from __future__ import annotations

from usage_limits.registry import collect_provider, list_providers


def test_list_providers_exposes_first_party_provider_order() -> None:
    providers = list_providers()
    # Index-based checks: position 7 was "opencode", now 7="opencode-go", 8="opencode-zen"
    assert providers[7].provider == "opencode-go"
    assert providers[7].display_name == "OpenCode Go"
    assert providers[7].active is True
    assert providers[7].source == "builtin"

    assert providers[8].provider == "opencode-zen"
    assert providers[8].display_name == "OpenCode Zen"
    assert providers[8].active is True
    assert providers[8].source == "builtin"

    assert providers[9].provider == "openrouter"
    assert providers[10].provider == "qoder"

    # Check trae is present and active
    trae_idx = next(i for i, p in enumerate(providers) if p.provider == "trae")
    assert providers[trae_idx].active is True
    assert providers[trae_idx].source == "builtin"

    # Check openrouter is inactive
    openrouter_idx = next(i for i, p in enumerate(providers) if p.provider == "openrouter")
    assert providers[openrouter_idx].active is False
    assert providers[openrouter_idx].source == "builtin"


def test_collect_provider_sets_account_for_provider_account() -> None:
    snap = collect_provider("claude")
    assert snap.account is not None
    assert snap.account == "default"
