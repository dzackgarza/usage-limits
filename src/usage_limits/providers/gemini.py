"""Gemini CLI usage limits provider."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from otlp_collector.db import DEFAULT_DB_PATH

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class GeminiProvider(UsageProvider):
    """Gemini CLI usage tracker."""

    slug = "gemini"
    name = "Gemini CLI"
    state_dir = "gemini_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    DEFAULT_DAILY_LIMIT = 1000

    def provider_name(self) -> str:
        return "Gemini CLI"

    def fetch_raw(self) -> dict[str, Any]:
        """Count today's Gemini CLI API requests from the otlp-collector DB."""
        today = datetime.now(UTC).date().isoformat()
        if not DEFAULT_DB_PATH.exists():
            return {"count": 0}
        with sqlite3.connect(DEFAULT_DB_PATH) as conn:
            row = conn.execute(
                """
                SELECT count(*) FROM logs
                WHERE date(time_unix_nano / 1000000000, 'unixepoch') = ?
                  AND json_extract(resource_attributes, '$."service.name"') = 'gemini-cli'
                  AND json_extract(attributes, '$."event.name"') = 'gemini_cli.api_request'
                """,
                (today,),
            ).fetchone()
        return {"count": row[0] if row else 0}

    def to_rows(self, raw: Any) -> list[UsageRow]:
        request_count = raw.get("count", 0)
        pct_used = (
            (request_count / self.DEFAULT_DAILY_LIMIT * 100)
            if self.DEFAULT_DAILY_LIMIT > 0
            else 0.0
        )
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return [UsageRow(identifier="Gemini CLI (daily)", pct_used=pct_used, reset_at=tomorrow)]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        daily_row = next((r for r in rows if "daily" in r.identifier), None)
        if daily_row and daily_row.pct_used == 0:
            self.send_ntfy(
                "Gemini CLI Daily Reset",
                f"Gemini CLI daily limit reset!\n\n{self.DEFAULT_DAILY_LIMIT} requests available.",
                tags="white_check_mark,rocket",
            )
