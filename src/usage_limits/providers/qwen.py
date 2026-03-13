"""Qwen usage limits provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from usage_limits.base import UsageProvider
from usage_limits.storage import TraceStore
from usage_limits.table import UsageRow


class QwenProvider(UsageProvider):
    """Qwen Code usage checker."""

    slug = "qwen"
    name = "Qwen Code"
    state_dir = "qwen_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    FREE_DAILY_LIMIT = 1000

    def provider_name(self) -> str:
        return "Qwen"

    def fetch_raw(self) -> dict[str, Any]:
        """Fetch today's Qwen Code request count from the OTLP sink DB."""
        counts = TraceStore().get_daily_counts(provider="qwen")
        today = datetime.now(UTC).date().isoformat()
        return {"count": counts.get(today, 0)}

    def to_rows(self, raw: Any) -> list[UsageRow]:
        request_count = raw.get("count", 0)
        pct_used = (
            (request_count / self.FREE_DAILY_LIMIT * 100) if self.FREE_DAILY_LIMIT > 0 else 0.0
        )
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return [UsageRow(identifier="Qwen (daily)", pct_used=pct_used, reset_at=tomorrow)]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        daily_row = next((r for r in rows if "daily" in r.identifier), None)
        if daily_row and daily_row.pct_used == 0:
            self.send_ntfy(
                "Qwen Daily Reset",
                f"Qwen Code daily limit reset!\n\n{self.FREE_DAILY_LIMIT} requests available.",
                tags="white_check_mark,rocket",
            )
