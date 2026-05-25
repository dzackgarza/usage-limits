"""Rendering tests for provider snapshots with account fields."""

from io import StringIO

from rich.console import Console

from usage_limits.contracts import ProviderSnapshot
from usage_limits.rendering import render_provider_snapshot
from usage_limits.table import UsageRow


def test_render_provider_snapshot_includes_account_in_title() -> None:
    """Rendering shows account identifier for multi-account providers."""
    snap = ProviderSnapshot(
        provider="antigravity",
        display_name="Antigravity",
        status="ok",
        account="user@example.com",
        rows=[
            UsageRow(
                identifier="Gemini 3.5 Flash (High)",
                pct_used=40.0,
                reset_at=None,
            )
        ],
    )
    buf = StringIO()
    console = Console(file=buf, force_terminal=False)
    render_provider_snapshot(snap, console=console)
    output = buf.getvalue()
    assert "user@example.com" in output


def test_render_provider_snapshot_omits_default_account() -> None:
    """Rendering does NOT show 'default' account identifier for single-account providers."""
    snap = ProviderSnapshot(
        provider="claude",
        display_name="Claude Code",
        status="ok",
        account="default",
        rows=[
            UsageRow(
                identifier="Claude (5h)",
                pct_used=50.0,
                reset_at=None,
            )
        ],
    )
    buf = StringIO()
    console = Console(file=buf, force_terminal=False)
    render_provider_snapshot(snap, console=console)
    output = buf.getvalue()
    assert "default" not in output


def test_render_provider_snapshot_without_account_shows_no_account() -> None:
    """Rendering works when account is None (backward compat)."""
    snap = ProviderSnapshot(
        provider="test",
        display_name="Test",
        status="ok",
        account=None,
        rows=[
            UsageRow(
                identifier="Test (24h)",
                pct_used=0.0,
                reset_at=None,
            )
        ],
    )
    buf = StringIO()
    console = Console(file=buf, force_terminal=False)
    render_provider_snapshot(snap, console=console)
    output = buf.getvalue()
    assert "Test" in output
