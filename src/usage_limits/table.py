"""Shared usage table data models and Rich table renderer."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, computed_field
from rich.console import Console
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table

__all__ = [
    "ModelAvailability",
    "UsageRow",
    "UsageTable",
]


class ModelAvailability(BaseModel):
    """Availability status for a single model or provider."""

    name: str
    """Display name, e.g. 'Claude', 'Codex', 'Antigravity: Flash (All)'."""

    available_now: bool
    """True when the provider/model can be used right now."""

    available_when: datetime | None = None
    """When it next becomes available; None means it is available now."""

    model_config = ConfigDict(frozen=True)


class UsageRow(BaseModel):
    """A single row in the unified usage table."""

    identifier: str
    """Human label, e.g. 'Claude (5h)', 'Amp', 'Antigravity: Gemini 2.5 Pro'."""

    pct_used: float
    """Percentage consumed, 0.0-100.0."""

    reset_at: datetime | None = None
    """UTC reset timestamp; None = not applicable or already at full capacity."""

    model_config = ConfigDict(frozen=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_exhausted(self) -> bool:
        """True when usage is at or above 100%."""
        return self.pct_used >= 100.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def time_until_reset(self) -> str:
        """Human-readable countdown to reset_at, or empty string if unset."""
        if self.reset_at is None:
            return ""
        delta = self.reset_at - datetime.now(UTC)
        if delta.total_seconds() <= 0:
            return "now"
        total_hrs = int(delta.total_seconds() / 3600)
        mins = int((delta.total_seconds() % 3600) / 60)
        if total_hrs >= 24:
            days = total_hrs // 24
            hrs = total_hrs % 24
            return f"in {days}d {hrs}h"
        return f"in {total_hrs}h {mins}m"


class UsageTable:
    """Renders a uniform 4-column usage table for any provider."""

    PCT_WIDTH = 5  # " 99%" + leading space
    TIME_WIDTH = 12  # "in 30d 12h"
    PADDING = 8  # padding=(0,1) x 4 columns x 2 sides

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def render(self, rows: list[UsageRow], title: str = "Usage Limits") -> None:
        """Render the usage table inside a titled panel."""
        if not rows:
            self.console.print("[yellow]No data available[/yellow]")
            return

        self.console.print(Panel(f"[bold]{title}[/bold]", border_style="cyan"))
        self.console.print()

        max_id_len = max(len(r.identifier) for r in rows)
        # Let bar shrink to 0 rather than overflowing the terminal.
        bar_width = max(
            0,
            self.console.width - max_id_len - self.PCT_WIDTH - self.TIME_WIDTH - self.PADDING,
        )

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column(
            "Identifier", style="bold", width=max_id_len, overflow="ellipsis", no_wrap=True
        )
        table.add_column("Pct", width=self.PCT_WIDTH, justify="right", no_wrap=True)
        if bar_width:
            table.add_column("Bar", width=bar_width, no_wrap=True)
        table.add_column("Time", width=self.TIME_WIDTH, no_wrap=True)

        for row in rows:
            color = self._bar_color(row.pct_used)
            pct_str = f"{int(row.pct_used):>4}%"
            if bar_width:
                bar = ProgressBar(
                    total=100,
                    completed=row.pct_used,
                    width=bar_width,
                    style="dim",
                    complete_style=color,
                    finished_style=color,
                )
                table.add_row(row.identifier, pct_str, bar, row.time_until_reset)
            else:
                table.add_row(row.identifier, pct_str, row.time_until_reset)

        self.console.print(table)
        self.console.print()

    @staticmethod
    def _bar_color(pct: float) -> str:
        if pct >= 100:
            return "red"
        if pct >= 80:
            return "yellow"
        return "green"
