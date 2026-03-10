"""OpenRouter usage limits provider.

OpenRouter does NOT expose free-tier request counts via its API (only credits
are tracked). fetch_raw() is intentionally not implemented — a mechanism to
count daily free-tier requests is needed that does not rely on third-party
observability tooling.

Known constraints:
- Free tier: 50 req/day if credits were never purchased; 1000 req/day otherwise.
- Daily limit resets at UTC midnight.
- OpenRouter API tracks credits, not request counts.

TODO: Implement fetch_raw() with a request-counting mechanism.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class OpenRouterProvider(UsageProvider):
    """OpenRouter daily request quota tracker.

    Free tier: 50 req/day (never purchased credits) or 1000 req/day (credits
    purchased at least once). Resets at UTC midnight.
    """

    slug = "openrouter"
    name = "OpenRouter"
    state_dir = "openrouter_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    FREE_DAILY_LIMIT = 1000  # 1000/day if credits ever purchased; 50/day if never paid

    def provider_name(self) -> str:
        return "OpenRouter"

    def fetch_raw(self) -> dict[str, Any]:
        """Fetch today's OpenRouter request count.

        NOT IMPLEMENTED. Must return {"count": N} where N is the number of
        free-tier model requests made today (UTC).
        """
        raise NotImplementedError(
            "OpenRouter does not expose request counts via its API. "
            "A tracking mechanism needs to be implemented."
        )

    def to_rows(self, raw: Any) -> list[UsageRow]:
        request_count = raw.get("count", 0)
        pct_used = (
            (request_count / self.FREE_DAILY_LIMIT * 100) if self.FREE_DAILY_LIMIT > 0 else 0.0
        )
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return [UsageRow(identifier="OpenRouter (daily)", pct_used=pct_used, reset_at=tomorrow)]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Daily limit resets automatically at UTC midnight — no anchoring needed."""
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Fire when daily limit is fresh (0 requests used)."""
        daily_row = next((r for r in rows if "daily" in r.identifier), None)
        if daily_row and daily_row.pct_used == 0:
            self.send_ntfy(
                "OpenRouter Daily Reset",
                f"OpenRouter daily limit reset!\n\n{self.FREE_DAILY_LIMIT} requests available.",
                tags="white_check_mark,rocket",
            )

    def _handle_notifications(self, rows: list[UsageRow]) -> None:
        """Schedule notification when daily limit is exhausted."""
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
