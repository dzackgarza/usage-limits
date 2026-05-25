"""Rich renderers for normalized usage_limits contracts."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from usage_limits.contracts import ProviderSnapshot, UsageCollection
from usage_limits.table import UsageTable

__all__ = ["render_collection", "render_provider_snapshot"]


def _display_title(snapshot: ProviderSnapshot) -> str:
    """Return the display title, appending account identifier when relevant."""
    base = snapshot.display_name
    if snapshot.account and snapshot.account != "default":
        return f"{base} ({snapshot.account})"
    return base


def render_provider_snapshot(
    snapshot: ProviderSnapshot,
    *,
    console: Console | None = None,
) -> None:
    """Render one provider snapshot."""
    active_console = console or Console()
    title = _display_title(snapshot)
    if snapshot.status == "error":
        message = "\n".join(error.message for error in snapshot.errors) or "Unknown provider error."
        active_console.print(
            Panel(
                message,
                title=f"{title} ({snapshot.provider})",
                border_style="red",
            )
        )
        active_console.print()
        return

    if snapshot.status == "rate_limited":
        message = "\n".join(error.message for error in snapshot.errors) or "Rate limited."
        active_console.print(
            Panel(
                message,
                title=f"{title} ({snapshot.provider})",
                border_style="yellow",
            )
        )
        active_console.print()
        return

    UsageTable(console=active_console).render(snapshot.rows, title=title)


def render_collection(collection: UsageCollection, *, console: Console | None = None) -> None:
    """Render all provider snapshots in sequence."""
    active_console = console or Console()
    for snapshot in collection.providers:
        render_provider_snapshot(snapshot, console=active_console)
