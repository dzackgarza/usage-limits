"""Registry tests for the canonical provider surface."""

from __future__ import annotations

from usage_limits.registry import list_providers


def test_list_providers_exposes_first_party_provider_order() -> None:
    providers = list_providers()
    assert [provider.provider for provider in providers[:6]] == [
        "antigravity",
        "claude",
        "codex",
        "ollama",
        "opencode",
        "openrouter",
    ]
    assert providers[0].display_name == "Antigravity"
    assert providers[4].active is True
    assert providers[5].provider == "openrouter"
    assert providers[5].active is False
    assert providers[5].source == "builtin"
