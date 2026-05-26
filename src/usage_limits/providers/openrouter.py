"""OpenRouter usage limits provider."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

from usage_limits.base import ProviderAccount
from usage_limits.table import UsageRow


class OpenRouterRaw(TypedDict):
    count: int


class OpenRouterProvider(ProviderAccount):
    """OpenRouter daily request quota tracker.

    Free tier: 50 req/day (never purchased credits) or 1000 req/day (credits
    purchased at least once). Resets at UTC midnight.
    """

    slug = "openrouter"
    name = "OpenRouter"
    state_dir = "openrouter_usage"

    # Default — override via config
    FREE_DAILY_LIMIT = 1000

    def provider_name(self) -> str:
        return "OpenRouter"

    def _state_file(self) -> Path:
        from usage_limits.config import resolve_path
        from usage_limits.config import settings as _cfg

        return resolve_path(_cfg.paths.openrouter_state_file)

    def fetch_raw(self) -> OpenRouterRaw:
        state_file = self._state_file()
        state: dict[str, int] = json.loads(state_file.read_text())
        today = datetime.now(UTC).date().isoformat()
        return {"count": state[today]}

    def to_rows(self, raw: OpenRouterRaw) -> list[UsageRow]:
        request_count = raw["count"]
        pct_used = (
            (request_count / self.FREE_DAILY_LIMIT * 100) if self.FREE_DAILY_LIMIT > 0 else 0.0
        )
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return [UsageRow(identifier="OpenRouter (daily)", pct_used=pct_used, reset_at=tomorrow)]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        daily_row = next((r for r in rows if "daily" in r.identifier), None)
        if daily_row and daily_row.pct_used == 0:
            self.send_ntfy(
                "OpenRouter Daily Reset",
                f"OpenRouter daily limit reset!\n\n{self.FREE_DAILY_LIMIT} requests available.",
                tags="white_check_mark,rocket",
            )

    def _handle_notifications(self, rows: list[UsageRow]) -> None:
        daily_row = next((r for r in rows if "daily" in r.identifier), None)
        if not daily_row or not daily_row.is_exhausted or not daily_row.reset_at:
            return
        notif_id = f"openrouter-daily-{int(daily_row.reset_at.timestamp())}"
        if self._notification_scheduled(notif_id):
            print("i  Notification already scheduled")
            return
        success, msg = self._schedule_notification(
            reset_dt=daily_row.reset_at,
            summary=f"Daily request limit reset ({self.FREE_DAILY_LIMIT} requests)",
            notif_id=notif_id,
            title="OpenRouter Daily Reset",
        )
        if success:
            print(f"🔔 Notification scheduled for {msg}")
        else:
            print(f"✗ Failed to schedule: {msg}")
