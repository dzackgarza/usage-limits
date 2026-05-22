"""Registry tests for the canonical provider surface."""

from __future__ import annotations

from usage_limits.registry import list_providers


def test_list_providers_exposes_first_party_provider_order() -> None:
    providers = list_providers()
    assert [provider.provider for provider in providers[:8]] == [
        "antigravity",
        "claude",
        "codex",
        "copilot",
        "cursor",
        "kiro",
        "ollama",
        "opencode",
    ]
    assert providers[0].display_name == "Antigravity"
    assert providers[4].active is True
    assert providers[5].provider == "kiro"
    assert providers[5].active is True
    assert providers[6].provider == "ollama"
    assert providers[6].active is True
    assert providers[7].provider == "opencode"
    assert providers[7].active is True
    # Check openrouter is inactive
    openrouter_idx = next(i for i, p in enumerate(providers) if p.provider == "openrouter")
    assert providers[openrouter_idx].active is False
    assert providers[openrouter_idx].source == "builtin"
