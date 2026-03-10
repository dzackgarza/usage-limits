"""Typer entrypoints for usage_limits."""

from __future__ import annotations

import json

import typer

from usage_limits.contracts import AvailabilityCollection, UsageCollection
from usage_limits.registry import collect_all, collect_provider, list_providers
from usage_limits.rendering import render_collection, render_provider_snapshot

__all__ = [
    "amp_main",
    "antigravity_main",
    "app",
    "claude_main",
    "codex_main",
    "main",
    "ollama_main",
    "openrouter_main",
    "qwen_main",
]


app = typer.Typer(
    add_completion=False,
    help="Collect and render normalized usage-limit data across providers.",
    no_args_is_help=True,
)
providers_app = typer.Typer(
    add_completion=False,
    help="Inspect registered providers.",
    no_args_is_help=True,
)
app.add_typer(providers_app, name="providers")

PROVIDER_OPTION = typer.Option(None, "--provider", help="Provider slug to collect.")
INSPECT_PROVIDER_OPTION = typer.Option(None, "--provider", help="Provider slug to inspect.")
TABLE_PROVIDER_OPTION = typer.Option(None, "--provider", help="Provider slug to render.")
ALL_COLLECT_OPTION = typer.Option(False, "--all", help="Collect all registered providers.")
ALL_AVAILABILITY_OPTION = typer.Option(False, "--all", help="Inspect all registered providers.")
ALL_TABLE_OPTION = typer.Option(False, "--all", help="Render all registered providers.")
JSON_OPTION = typer.Option(True, "--json/--no-json", help="Emit structured JSON.")
PROVIDERS_JSON_OPTION = typer.Option(False, "--json", help="Emit provider metadata as JSON.")
NOTIFY_OPTION = typer.Option(False, "--notify", help="Send provider notifications.")
ANCHOR_OPTION = typer.Option(False, "--anchor", help="Allow providers to anchor idle windows.")
ALIAS_JSON_OPTION = typer.Option(
    False,
    "--json",
    "-j",
    help="Emit the provider snapshot as JSON.",
)
ALIAS_AVAILABILITY_OPTION = typer.Option(
    False,
    "--availability",
    "-a",
    help="Emit provider availability as JSON.",
)


def _emit_json(payload: object) -> None:
    """Write a JSON payload to stdout."""
    if hasattr(payload, "model_dump"):
        typer.echo(json.dumps(payload.model_dump(mode="json"), indent=2))
        return
    typer.echo(json.dumps(payload, indent=2))


def _resolve_selected_providers(provider: list[str] | None, all_providers: bool) -> list[str]:
    """Validate provider selection flags."""
    if all_providers:
        if provider:
            raise typer.BadParameter("Use either --all or --provider, not both.")
        return [registered.provider for registered in list_providers()]
    if not provider:
        raise typer.BadParameter("Pass --provider at least once or use --all.")
    return provider


@providers_app.command("list")
def providers_list(
    json_output: bool = PROVIDERS_JSON_OPTION,
) -> None:
    """List registered providers."""
    providers = list_providers()
    if json_output:
        _emit_json([provider.model_dump(mode="json") for provider in providers])
        return
    for provider in providers:
        typer.echo(f"{provider.provider}\t{provider.display_name}\t{provider.source}")


@app.command()
def collect(
    provider: list[str] | None = PROVIDER_OPTION,
    all_providers: bool = ALL_COLLECT_OPTION,
    json_output: bool = JSON_OPTION,
    notify: bool = NOTIFY_OPTION,
    anchor: bool = ANCHOR_OPTION,
) -> None:
    """Collect normalized usage data."""
    selected = _resolve_selected_providers(provider, all_providers)
    collection = collect_all(selected, notify=notify, anchor=anchor)
    if json_output:
        _emit_json(collection)
        return
    render_collection(collection)


@app.command()
def availability(
    provider: list[str] | None = INSPECT_PROVIDER_OPTION,
    all_providers: bool = ALL_AVAILABILITY_OPTION,
    json_output: bool = JSON_OPTION,
) -> None:
    """Collect read-only availability data."""
    selected = _resolve_selected_providers(provider, all_providers)
    collection = collect_all(selected, notify=False, anchor=False)
    availability_collection = AvailabilityCollection.from_usage_collection(collection)
    if json_output:
        _emit_json(availability_collection)
        return
    for snapshot in availability_collection.providers:
        if snapshot.status == "error":
            typer.echo(f"{snapshot.provider}\terror")
            continue
        for availability_entry in snapshot.availability:
            when = (
                availability_entry.available_when.isoformat()
                if availability_entry.available_when
                else "now"
            )
            state = "available" if availability_entry.available_now else "blocked"
            typer.echo(f"{availability_entry.name}\t{state}\t{when}")


@app.command()
def table(
    provider: list[str] | None = TABLE_PROVIDER_OPTION,
    all_providers: bool = ALL_TABLE_OPTION,
    notify: bool = NOTIFY_OPTION,
    anchor: bool = ANCHOR_OPTION,
) -> None:
    """Render usage data with Rich tables."""
    selected = _resolve_selected_providers(provider, all_providers)
    collection = collect_all(selected, notify=notify, anchor=anchor)
    render_collection(collection)


def _provider_alias(
    provider: str,
    *,
    supports_anchor: bool,
) -> None:
    """Run a single-provider alias command."""

    def command(
        json_output: bool = ALIAS_JSON_OPTION,
        availability: bool = ALIAS_AVAILABILITY_OPTION,
        notify: bool = NOTIFY_OPTION,
        anchor: bool = ANCHOR_OPTION,
    ) -> None:
        provider_snapshot = collect_provider(
            provider,
            notify=notify,
            anchor=anchor if supports_anchor else False,
        )
        if availability:
            availability_snapshot = AvailabilityCollection.from_usage_collection(
                UsageCollection(providers=[provider_snapshot])
            ).providers[0]
            _emit_json(availability_snapshot.model_dump(mode="json"))
            return
        if json_output:
            _emit_json(provider_snapshot.model_dump(mode="json"))
            return
        render_provider_snapshot(provider_snapshot)

    typer.run(command)


def claude_main() -> None:
    _provider_alias("claude", supports_anchor=True)


def codex_main() -> None:
    _provider_alias("codex", supports_anchor=True)


def amp_main() -> None:
    _provider_alias("amp", supports_anchor=False)


def antigravity_main() -> None:
    _provider_alias("antigravity", supports_anchor=False)


def ollama_main() -> None:
    _provider_alias("ollama", supports_anchor=True)


def openrouter_main() -> None:
    _provider_alias("openrouter", supports_anchor=False)


def qwen_main() -> None:
    _provider_alias("qwen", supports_anchor=False)


def main() -> None:
    """Console script entrypoint."""
    app()
