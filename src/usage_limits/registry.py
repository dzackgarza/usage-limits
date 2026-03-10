"""Provider registry and orchestration helpers."""

from __future__ import annotations

from importlib.metadata import entry_points

from usage_limits.base import UsageProvider
from usage_limits.contracts import (
    ProviderError,
    ProviderSnapshot,
    RegisteredProvider,
    UsageCollection,
)
from usage_limits.providers import (
    AmpProvider,
    AntigravityProvider,
    ClaudeProvider,
    CodexProvider,
    OllamaProvider,
    OpenRouterProvider,
    QwenProvider,
)

__all__ = [
    "collect_all",
    "collect_provider",
    "get_provider_class",
    "list_providers",
]


FIRST_PARTY_PROVIDER_CLASSES: tuple[type[UsageProvider], ...] = (
    AmpProvider,
    AntigravityProvider,
    ClaudeProvider,
    CodexProvider,
    OllamaProvider,
    OpenRouterProvider,
    QwenProvider,
)

FIRST_PARTY_PROVIDERS: dict[str, type[UsageProvider]] = {
    provider_class.slug: provider_class for provider_class in FIRST_PARTY_PROVIDER_CLASSES
}


def _load_entry_point_providers() -> dict[str, type[UsageProvider]]:
    """Load external providers registered via Python entry points."""
    external: dict[str, type[UsageProvider]] = {}
    for entry_point in entry_points(group="usage_limits.providers"):
        loaded = entry_point.load()
        if not isinstance(loaded, type) or not issubclass(loaded, UsageProvider):
            continue
        slug = getattr(loaded, "slug", entry_point.name)
        if slug in FIRST_PARTY_PROVIDERS:
            continue
        external[slug] = loaded
    return external


def _provider_classes() -> dict[str, type[UsageProvider]]:
    """Return the complete provider registry."""
    providers = dict(FIRST_PARTY_PROVIDERS)
    for slug, provider_class in _load_entry_point_providers().items():
        providers.setdefault(slug, provider_class)
    return providers


def list_providers() -> list[RegisteredProvider]:
    """List builtin and external providers."""
    providers = [
        RegisteredProvider(
            provider=provider_class.slug,
            display_name=provider_class.name,
            module=provider_class.__module__,
            source="builtin",
        )
        for provider_class in FIRST_PARTY_PROVIDER_CLASSES
    ]

    for slug, provider_class in sorted(_load_entry_point_providers().items()):
        providers.append(
            RegisteredProvider(
                provider=slug,
                display_name=provider_class.name,
                module=provider_class.__module__,
                source="entry_point",
            )
        )

    return providers


def get_provider_class(provider: str) -> type[UsageProvider]:
    """Resolve a provider slug to its implementation class."""
    providers = _provider_classes()
    if provider not in providers:
        available = ", ".join(sorted(providers))
        raise ValueError(f"Unknown provider {provider!r}. Available providers: {available}")
    return providers[provider]


def _error_message(error: BaseException) -> str:
    """Normalize exception messages for the JSON contract."""
    if isinstance(error, SystemExit):
        code = error.code
        if isinstance(code, str) and code:
            return code
        if isinstance(code, int):
            return f"Provider exited with status {code}."
        return "Provider exited."
    message = str(error).strip()
    if message:
        return message
    return error.__class__.__name__


def _error_type(error: BaseException) -> str:
    """Map exceptions to stable error identifiers."""
    if isinstance(error, NotImplementedError):
        return "not_implemented"
    if isinstance(error, SystemExit):
        return "system_exit"
    return error.__class__.__name__.lower()


def _error_snapshot(
    provider_class: type[UsageProvider],
    error: BaseException,
) -> ProviderSnapshot:
    """Build a normalized error snapshot for a failed provider."""
    return ProviderSnapshot(
        provider=provider_class.slug,
        display_name=provider_class.name,
        status="error",
        errors=[ProviderError(type=_error_type(error), message=_error_message(error))],
    )


def collect_provider(
    provider: str,
    *,
    notify: bool = False,
    anchor: bool = False,
) -> ProviderSnapshot:
    """Collect a normalized snapshot for one provider."""
    provider_class = get_provider_class(provider)
    try:
        return provider_class().collect_snapshot(notify=notify, anchor=anchor)
    except BaseException as error:
        return _error_snapshot(provider_class, error)


def collect_all(
    providers: list[str] | None = None,
    *,
    notify: bool = False,
    anchor: bool = False,
) -> UsageCollection:
    """Collect a normalized snapshot for one or more providers."""
    selected = providers or [provider.provider for provider in list_providers()]
    snapshots = [
        collect_provider(provider, notify=notify, anchor=anchor) for provider in selected
    ]
    return UsageCollection(providers=snapshots)
