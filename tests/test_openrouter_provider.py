"""Tests for OpenRouterProvider correctness.

OpenRouter does NOT expose usage limits via API.
This provider counts local OTLP events for request tracking.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from usage_limits.providers.openrouter import OpenRouterProvider
from usage_limits.table import UsageRow


def test_notify_always_fires_on_fresh_daily_limit() -> None:
    """notify_always should fire when daily limit has reset (0% used)."""
    provider = OpenRouterProvider()
    sent: list[tuple[str, str]] = []

    def capture(title: str, message: str, **kwargs: object) -> tuple[bool, None]:
        sent.append((title, message))
        return True, None

    provider.send_ntfy = capture  # type: ignore[method-assign]

    reset_at = (datetime.now(UTC) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    row = UsageRow(identifier="OpenRouter (daily, 1000 limit)", pct_used=0.0, reset_at=reset_at)

    provider.notify_always([row])

    assert len(sent) == 1
    assert "Daily Reset" in sent[0][0]


def test_notify_always_skips_when_usage_exists() -> None:
    """notify_always should not fire when usage > 0%."""
    provider = OpenRouterProvider()
    sent: list[tuple[str, str]] = []

    def capture(title: str, message: str, **kwargs: object) -> tuple[bool, None]:
        sent.append((title, message))
        return True, None

    provider.send_ntfy = capture  # type: ignore[method-assign]

    reset_at = (datetime.now(UTC) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    row = UsageRow(identifier="OpenRouter (daily, 1000 limit)", pct_used=25.0, reset_at=reset_at)

    provider.notify_always([row])

    assert sent == [], "Should not notify when usage > 0%"


def test_to_rows_uses_default_limit() -> None:
    """to_rows should use 1000/day default limit."""
    provider = OpenRouterProvider()
    raw = {"count": 250, "credit_info": {}}
    rows = provider.to_rows(raw)

    assert len(rows) == 1
    assert rows[0].pct_used == 25.0  # 250 / 1000 * 100
    assert "1000 limit" in rows[0].identifier
    assert provider._resolved_limit == 1000


def test_to_rows_uses_free_tier_limit() -> None:
    """to_rows should use 50/day for free tier (never paid)."""
    provider = OpenRouterProvider()
    raw = {"count": 25, "credit_info": {"is_free_tier": True}}
    rows = provider.to_rows(raw)

    assert len(rows) == 1
    assert rows[0].pct_used == 50.0  # 25 / 50 * 100
    assert "50 limit" in rows[0].identifier
    assert provider._resolved_limit == 50


def test_to_rows_respects_custom_limit_env() -> None:
    """to_rows should respect OPENROUTER_DAILY_LIMIT env var."""
    provider = OpenRouterProvider()
    raw = {"count": 10, "credit_info": {}}

    old_value = os.environ.get("OPENROUTER_DAILY_LIMIT")
    try:
        os.environ["OPENROUTER_DAILY_LIMIT"] = "200"
        rows = provider.to_rows(raw)

        assert len(rows) == 1
        assert rows[0].pct_used == 5.0  # 10 / 200 * 100
        assert "200 limit" in rows[0].identifier
        assert provider._resolved_limit == 200
    finally:
        if old_value is not None:
            os.environ["OPENROUTER_DAILY_LIMIT"] = old_value
        else:
            os.environ.pop("OPENROUTER_DAILY_LIMIT", None)


def test_to_rows_handles_zero_count() -> None:
    """to_rows should handle zero request count."""
    provider = OpenRouterProvider()
    raw = {"count": 0, "credit_info": {}}
    rows = provider.to_rows(raw)

    assert len(rows) == 1
    assert rows[0].pct_used == 0.0
    assert rows[0].reset_at is not None


def test_to_rows_handles_exhausted_limit() -> None:
    """to_rows should mark as exhausted when at 100%."""
    provider = OpenRouterProvider()
    raw = {"count": 1000, "credit_info": {}}
    rows = provider.to_rows(raw)

    assert len(rows) == 1
    assert rows[0].pct_used == 100.0
    assert rows[0].is_exhausted


def test_to_rows_handles_over_limit() -> None:
    """to_rows should handle usage exceeding limit."""
    provider = OpenRouterProvider()
    raw = {"count": 1500, "credit_info": {}}
    rows = provider.to_rows(raw)

    assert len(rows) == 1
    assert rows[0].pct_used == 150.0
    assert rows[0].is_exhausted
