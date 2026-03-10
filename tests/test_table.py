"""Tests for usage_limits.table — UsageRow, ModelAvailability, UsageTable."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from rich.console import Console

from usage_limits.table import ModelAvailability, UsageRow, UsageTable

# ---------------------------------------------------------------------------
# UsageRow
# ---------------------------------------------------------------------------


class TestUsageRowIsExhausted:
    def test_below_100_not_exhausted(self) -> None:
        row = UsageRow(identifier="X", pct_used=99.9)
        assert row.is_exhausted is False

    def test_exactly_100_is_exhausted(self) -> None:
        row = UsageRow(identifier="X", pct_used=100.0)
        assert row.is_exhausted is True

    def test_above_100_is_exhausted(self) -> None:
        row = UsageRow(identifier="X", pct_used=120.0)
        assert row.is_exhausted is True

    def test_zero_not_exhausted(self) -> None:
        row = UsageRow(identifier="X", pct_used=0.0)
        assert row.is_exhausted is False


class TestUsageRowTimeUntilReset:
    def test_no_reset_at_returns_empty_string(self) -> None:
        row = UsageRow(identifier="X", pct_used=50.0)
        assert row.time_until_reset == ""

    def test_past_reset_returns_now(self) -> None:
        past = datetime.now(UTC) - timedelta(seconds=1)
        row = UsageRow(identifier="X", pct_used=50.0, reset_at=past)
        assert row.time_until_reset == "now"

    def test_future_hours_and_minutes(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=3, minutes=25)
        row = UsageRow(identifier="X", pct_used=50.0, reset_at=future)
        # Allow ±1 minute drift from test execution time
        assert row.time_until_reset in ("in 3h 24m", "in 3h 25m", "in 3h 26m")

    def test_future_days_format(self) -> None:
        future = datetime.now(UTC) + timedelta(days=2, hours=5)
        row = UsageRow(identifier="X", pct_used=50.0, reset_at=future)
        # 2 days 5 hours
        assert row.time_until_reset.startswith("in 2d")

    def test_exactly_one_hour(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=1)
        row = UsageRow(identifier="X", pct_used=50.0, reset_at=future)
        assert row.time_until_reset in ("in 0h 59m", "in 1h 0m", "in 1h 1m")

    def test_under_one_minute(self) -> None:
        future = datetime.now(UTC) + timedelta(seconds=30)
        row = UsageRow(identifier="X", pct_used=50.0, reset_at=future)
        assert row.time_until_reset == "in 0h 0m"


# ---------------------------------------------------------------------------
# ModelAvailability
# ---------------------------------------------------------------------------


class TestModelAvailability:
    def test_available_now(self) -> None:
        m = ModelAvailability(name="Claude", available_now=True)
        assert m.available_now is True
        assert m.available_when is None

    def test_not_available_with_time(self) -> None:
        when = datetime.now(UTC) + timedelta(hours=2)
        m = ModelAvailability(name="Claude", available_now=False, available_when=when)
        assert m.available_now is False
        assert m.available_when == when

    def test_frozen(self) -> None:
        m = ModelAvailability(name="Claude", available_now=True)
        with pytest.raises(ValidationError):
            m.name = "Other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# UsageTable._bar_color
# ---------------------------------------------------------------------------


class TestBarColor:
    def test_green_below_80(self) -> None:
        assert UsageTable._bar_color(0.0) == "green"
        assert UsageTable._bar_color(50.0) == "green"
        assert UsageTable._bar_color(79.9) == "green"

    def test_yellow_80_to_99(self) -> None:
        assert UsageTable._bar_color(80.0) == "yellow"
        assert UsageTable._bar_color(95.0) == "yellow"
        assert UsageTable._bar_color(99.9) == "yellow"

    def test_red_at_100(self) -> None:
        assert UsageTable._bar_color(100.0) == "red"
        assert UsageTable._bar_color(120.0) == "red"


# ---------------------------------------------------------------------------
# UsageTable.render — output correctness
# ---------------------------------------------------------------------------


def _capture_render(rows: list[UsageRow], title: str = "Test") -> str:
    """Render to a fixed-width in-memory console and return the text."""
    console = Console(width=120, force_terminal=True, highlight=False)
    with console.capture() as cap:
        UsageTable(console=console).render(rows, title=title)
    return cap.get()


class TestUsageTableRender:
    def test_empty_rows_prints_no_data(self) -> None:
        output = _capture_render([])
        assert "No data" in output

    def test_identifier_appears_in_output(self) -> None:
        row = UsageRow(identifier="Claude 3.5 Sonnet", pct_used=42.0)
        output = _capture_render([row])
        assert "Claude 3.5 Sonnet" in output

    def test_pct_appears_in_output(self) -> None:
        row = UsageRow(identifier="Amp", pct_used=75.0)
        output = _capture_render([row])
        assert "75%" in output

    def test_title_appears_in_output(self) -> None:
        row = UsageRow(identifier="X", pct_used=10.0)
        output = _capture_render([row], title="My Provider")
        assert "My Provider" in output

    def test_multiple_rows_all_present(self) -> None:
        rows = [
            UsageRow(identifier="Model A", pct_used=10.0),
            UsageRow(identifier="Model B", pct_used=90.0),
            UsageRow(identifier="Model C", pct_used=100.0),
        ]
        output = _capture_render(rows)
        assert "Model A" in output
        assert "Model B" in output
        assert "Model C" in output

    def test_reset_time_appears_when_set(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=2, minutes=15)
        row = UsageRow(identifier="X", pct_used=50.0, reset_at=future)
        output = _capture_render([row])
        assert "in 2h" in output

    def test_zero_pct_renders(self) -> None:
        row = UsageRow(identifier="Fresh", pct_used=0.0)
        output = _capture_render([row])
        assert "0%" in output

    def test_100_pct_renders(self) -> None:
        row = UsageRow(identifier="Exhausted", pct_used=100.0)
        output = _capture_render([row])
        assert "100%" in output
