"""Whitelist framework-driven usage-limits symbols for vulture."""

from usage_limits.cli import (
    amp_main,
    antigravity_main,
    app_main,
    claude_main,
    codex_main,
    gemini_main,
    ollama_main,
    openrouter_main,
    providers_list,
    qwen_main,
)
from usage_limits.contracts import (
    AvailabilityCollection,
    AvailabilitySnapshot,
    ProviderError,
    ProviderSnapshot,
    RegisteredProvider,
    UsageCollection,
)
from usage_limits.table import ModelAvailability, UsageRow

_ = amp_main
_ = antigravity_main
_ = app_main
_ = claude_main
_ = codex_main
_ = gemini_main
_ = ollama_main
_ = openrouter_main
_ = providers_list
_ = qwen_main

_ = ProviderError.model_config
_ = ProviderSnapshot.model_config
_ = UsageCollection.model_config
_ = AvailabilitySnapshot.model_config
_ = AvailabilityCollection.model_config
_ = RegisteredProvider.model_config
_ = ModelAvailability.model_config
_ = UsageRow.model_config

_registered_provider_module = RegisteredProvider(
    provider="",
    display_name="",
    module="",
).module
