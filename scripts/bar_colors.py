"""Render progress bars at every percentile to check color thresholds."""

from datetime import UTC, datetime

from rich.console import Console

from usage_limits.table import UsageRow, UsageTable


def main() -> None:
    c = Console(width=100, color_system="truecolor")
    rows = [
        UsageRow(
            identifier=f"pct={pct}",
            pct_used=pct,
            reset_at=datetime(2026, 5, 25, tzinfo=UTC),
        )
        for pct in (0, 50, 79, 80, 95, 98, 99, 100)
    ]
    UsageTable(console=c).render(rows, title="Bar Color Thresholds")


if __name__ == "__main__":
    main()
