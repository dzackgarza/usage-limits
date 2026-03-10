"""Typer entrypoints for usage_limits."""

from __future__ import annotations

import json
from typing import Annotated

import typer

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
)
providers_app = typer.Typer(
    add_completion=False,
    help="Inspect registered providers.",
    no_args_is_help=True,
)
app.add_typer(providers_app, name="providers")


def _emit_json(payload: object) -> None:
    """Write a JSON payload to stdout."""
    if hasattr(payload, "model_dump"):
        typer.echo(json.dumps(payload.model_dump(mode="json"), indent=2))
        return
    typer.echo(json.dumps(payload, indent=2))


@providers_app.command("list")
def providers_list(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit provider metadata as JSON.")
    ] = False,
) -> None:
    """List registered providers."""
    providers = list_providers()
    if json_output:
        _emit_json([provider.model_dump(mode="json") for provider in providers])
        return
    for provider in providers:
        typer.echo(f"{provider.provider}\t{provider.display_name}\t{provider.source}")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    provider: Annotated[
        list[str] | None,
        typer.Option("--provider", "-p", help="Provider slug(s) to collect (default: all)."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", "-j", help="Emit the canonical JSON contract."),
    ] = False,
    notify: Annotated[
        bool,
        typer.Option("--notify", "-n", help="Send provider notifications."),
    ] = False,
    anchor: Annotated[
        bool,
        typer.Option("--anchor", "-a", help="Allow providers to anchor idle windows."),
    ] = False,
) -> None:
    """Collect and render usage data. Default is a Rich table of all providers."""
    if ctx.invoked_subcommand:
        return

    collection = collect_all(provider, notify=notify, anchor=anchor)

    if json_output:
        _emit_json(collection)
        return

    render_collection(collection)


def _provider_alias(
    provider: str,
    *,
    supports_anchor: bool,
) -> None:
    """Run a single-provider alias command."""

    def command(
        json_output: Annotated[
            bool,
            typer.Option("--json", "-j", help="Emit the provider snapshot as JSON."),
        ] = False,
        notify: Annotated[
            bool,
            typer.Option("--notify", "-n", help="Send provider notifications."),
        ] = False,
        anchor: Annotated[
            bool,
            typer.Option("--anchor", "-a", help="Allow providers to anchor idle windows."),
        ] = False,
    ) -> None:
        provider_snapshot = collect_provider(
            provider,
            notify=notify,
            anchor=anchor if supports_anchor else False,
        )
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
