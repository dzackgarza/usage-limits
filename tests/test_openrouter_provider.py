"""Tests for OpenRouterProvider correctness."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from usage_limits.providers.openrouter import OpenRouterProvider
from usage_limits.table import UsageRow


def _row(pct_used: float) -> UsageRow:
    reset_at = (datetime.now(UTC) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return UsageRow(identifier="OpenRouter (daily)", pct_used=pct_used, reset_at=reset_at)


def test_notify_always_never_fires_because_count_is_always_zero() -> None:
    """notify_always must be a no-op: OpenRouter always returns count=0, so pct_used
    is permanently 0 and firing a reset notification on every run would be spam."""
    provider = OpenRouterProvider()
    sent: list[tuple[str, str]] = []

    def capture(title: str, message: str, **kwargs: object) -> tuple[bool, None]:
        sent.append((title, message))
        return True, None

    provider.send_ntfy = capture  # type: ignore[method-assign]
    provider.notify_always([_row(pct_used=0.0)])
    provider.notify_always([_row(pct_used=0.0)])

    assert sent == [], "notify_always must never send a notification for OpenRouter"


def test_to_rows_uses_free_tier_limit_when_is_free_tier_true() -> None:
    """to_rows must select FREE_DAILY_LIMIT_NO_CREDITS (50) for free-tier users."""
    provider = OpenRouterProvider()
    raw = {"key_info": {"is_free_tier": True}, "count": 25}
    rows = provider.to_rows(raw)
    # 25 / 50 * 100 = 50.0
    assert rows[0].pct_used == 50.0
    assert provider._resolved_limit == 50


def test_to_rows_uses_paid_limit_when_is_free_tier_false() -> None:
    """to_rows must select FREE_DAILY_LIMIT (1000) for paid-tier users."""
    provider = OpenRouterProvider()
    raw = {"key_info": {"is_free_tier": False}, "count": 100}
    rows = provider.to_rows(raw)
    # 100 / 1000 * 100 = 10.0
    assert rows[0].pct_used == 10.0
    assert provider._resolved_limit == 1000
