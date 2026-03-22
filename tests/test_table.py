"""Tests for usage_limits.table — UsageRow and UsageTable rendering.

Focus: Tests that prove repository-owned rendering logic, not Pydantic behavior.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rich.console import Console

from usage_limits.table import ModelAvailability, UsageRow, UsageTable

# ---------------------------------------------------------------------------
# UsageRow - Repository-owned computed fields
# ---------------------------------------------------------------------------


class TestUsageRowIsExhausted:
    """Test the repository's exhaustion threshold logic (100%)."""

    def test_exactly_100_is_exhausted(self) -> None:
        """100% usage marks resource as exhausted."""
        row = UsageRow(identifier="X", pct_used=100.0)
        assert row.is_exhausted is True

    def test_above_100_is_exhausted(self) -> None:
        """Over 100% usage (overage) still marks as exhausted."""
        row = UsageRow(identifier="X", pct_used=120.0)
        assert row.is_exhausted is True


class TestUsageRowTimeUntilReset:
    """Test human-readable time formatting logic."""

    def test_no_reset_at_returns_empty_string(self) -> None:
        """No reset time means empty string (not applicable)."""
        row = UsageRow(identifier="X", pct_used=50.0)
        assert row.time_until_reset == ""

    def test_past_reset_returns_now(self) -> None:
        """Past reset times show as 'now'."""
        past = datetime.now(UTC) - timedelta(seconds=1)
        row = UsageRow(identifier="X", pct_used=50.0, reset_at=past)
        assert row.time_until_reset == "now"

    def test_future_days_format(self) -> None:
        """Multi-day resets use 'Xd Yh' format."""
        future = datetime.now(UTC) + timedelta(days=2, hours=5)
        row = UsageRow(identifier="X", pct_used=50.0, reset_at=future)
        assert row.time_until_reset.startswith("in 2d")


# ---------------------------------------------------------------------------
# ModelAvailability
# ---------------------------------------------------------------------------


class TestModelAvailability:
    """Test availability semantics."""

    def test_available_now(self) -> None:
        """available_now=True means available_when is None."""
        m = ModelAvailability(name="Claude", available_now=True)
        assert m.available_now is True
        assert m.available_when is None

    def test_not_available_with_time(self) -> None:
        """available_now=False must have available_when set."""
        future = datetime.now(UTC) + timedelta(hours=2)
        m = ModelAvailability(name="Claude", available_now=False, available_when=future)
        assert m.available_now is False
        assert m.available_when == future


# ---------------------------------------------------------------------------
# UsageTable Rendering
# ---------------------------------------------------------------------------


class TestUsageTableRendering:
    """Test that the table renderer produces correct output."""

    def test_empty_rows_prints_no_data(self) -> None:
        """Empty input shows 'No data available' message."""
        console = Console(force_terminal=True, width=80)
        with console.capture() as capture:
            UsageTable(console).render([])
        output = capture.get()
        assert "No data available" in output

    def test_identifier_appears_in_output(self) -> None:
        """Row identifiers appear in rendered table."""
        console = Console(force_terminal=True, width=80)
        rows = [UsageRow(identifier="Test Provider (5h)", pct_used=50.0, reset_at=None)]
        with console.capture() as capture:
            UsageTable(console).render(rows, title="Test")
        output = capture.get()
        assert "Test Provider (5h)" in output

    def test_pct_appears_as_integer(self) -> None:
        """Percentage appears as integer with % sign."""
        console = Console(force_terminal=True, width=80)
        rows = [UsageRow(identifier="Test", pct_used=75.5, reset_at=None)]
        with console.capture() as capture:
            UsageTable(console).render(rows, title="Test")
        output = capture.get()
        assert "75%" in output  # Should round to integer

    def test_title_appears_in_panel(self) -> None:
        """Custom title appears in panel header."""
        console = Console(force_terminal=True, width=80)
        rows = [UsageRow(identifier="Test", pct_used=50.0, reset_at=None)]
        with console.capture() as capture:
            UsageTable(console).render(rows, title="Custom Title")
        output = capture.get()
        assert "Custom Title" in output

    def test_multiple_rows_all_present(self) -> None:
        """All rows appear in multi-row output."""
        console = Console(force_terminal=True, width=80)
        rows = [
            UsageRow(identifier="Provider A (5h)", pct_used=25.0, reset_at=None),
            UsageRow(identifier="Provider B (7d)", pct_used=75.0, reset_at=None),
        ]
        with console.capture() as capture:
            UsageTable(console).render(rows, title="Test")
        output = capture.get()
        assert "Provider A (5h)" in output
        assert "Provider B (7d)" in output

    def test_reset_time_appears_when_set(self) -> None:
        """Reset timestamps appear in time column."""
        console = Console(force_terminal=True, width=80)
        future = datetime.now(UTC) + timedelta(hours=5)
        rows = [UsageRow(identifier="Test", pct_used=50.0, reset_at=future)]
        with console.capture() as capture:
            UsageTable(console).render(rows, title="Test")
        output = capture.get()
        assert "in 5h" in output or "in 4h" in output  # Allow ±1 min
