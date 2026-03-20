"""OpenRouter usage limits provider.

OpenRouter does NOT expose usage limits or daily request counts via API.
This provider tracks usage via local OpenTelemetry TRACES (spans) from the otlp-collector database.

Known constraints:
- Free tier: 50 req/day if credits were never purchased; 1000 req/day otherwise
- Daily limit resets at UTC midnight
- Credit balance available via API, but not usage limits

OTLP Telemetry Structure (Traces, not Logs):
- Table: spans (not logs)
- service.name: "openrouter" (from resource_attributes)
- Span attributes: gen_ai.request.model, gen_ai.provider.name, etc.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow

# otlp-collector database path
DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "otlp-collector" / "telemetry.db"


class OpenRouterProvider(UsageProvider):
    """OpenRouter daily request quota tracker via OTLP events."""

    slug = "openrouter"
    name = "OpenRouter"
    state_dir = "openrouter_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    FREE_DAILY_LIMIT: int = 1000  # 1000/day if credits ever purchased
    FREE_DAILY_LIMIT_NO_CREDITS: int = 50  # 50/day if never paid
    CREDIT_API_ENDPOINT: str = "https://openrouter.ai/api/v1/credits"

    def __init__(self) -> None:
        super().__init__()
        self.auth_file = Path.home() / ".local" / "share" / "opencode" / "auth.json"
        self._resolved_limit: int = self.FREE_DAILY_LIMIT

    def provider_name(self) -> str:
        return "OpenRouter"

    def get_credentials(self) -> dict[str, Any]:
        """Load API key from ~/.local/share/opencode/auth.json."""
        if not self.auth_file.exists():
            return {}
        try:
            data = json.loads(self.auth_file.read_text())
            if "openrouter" in data:
                entry = data["openrouter"]
                if isinstance(entry, dict):
                    return entry
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def fetch_raw(self) -> dict[str, Any]:
        """Fetch OpenRouter request count from otlp-collector DB and credit balance from API.

        OpenRouter does not expose usage limits via API, so we count local OTLP events from
        the otlp-collector telemetry database.

        Credit balance is fetched separately for informational purposes only.
        """
        # Count today's requests from otlp-collector DB
        request_count = self._count_today_requests()

        # Fetch credit balance (optional, for metadata)
        credit_info = self._fetch_credit_balance()

        return {
            "count": request_count,
            "credit_info": credit_info,
        }

    def _count_today_requests(self) -> int:
        """Count today's OpenRouter API requests from the otlp-collector DB.

        OpenRouter sends OpenTelemetry TRACES (spans), not logs.
        Queries the spans table for traces where:
        - service.name = 'openrouter' (from resource_attributes)
        """
        path = DEFAULT_DB_PATH
        today = datetime.now(UTC).date().isoformat()

        if not path.exists():
            return 0

        try:
            with sqlite3.connect(path) as conn:
                row = conn.execute(
                    """
                    SELECT count(*) FROM spans
                    WHERE date(start_time_unix_nano / 1000000000, 'unixepoch') = ?
                      AND json_extract(resource_attributes, '$."service.name"') = 'openrouter'
                    """,
                    (today,),
                ).fetchone()
            return row[0] if row else 0
        except (sqlite3.Error, Exception):
            return 0

    def _fetch_credit_balance(self) -> dict[str, Any]:
        """Fetch credit balance from OpenRouter API (optional metadata)."""
        creds = self.get_credentials()
        api_key = creds.get("key") or creds.get("token") if creds else None

        if not api_key:
            return {}

        try:
            resp = requests.get(
                self.CREDIT_API_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                return data.get("data", {}) if isinstance(data, dict) else {}
        except requests.RequestException:
            pass

        return {}

    def to_rows(self, raw: Any) -> list[UsageRow]:
        """Convert raw data to usage rows.

        OpenRouter free tier limits:
        - 50 req/day: Never purchased credits
        - 1000 req/day: Ever purchased credits (even $1)

        Since we can't determine which tier via API, we assume 1000/day default.
        Users can override via environment variable if needed.
        """
        request_count = raw.get("count", 0)
        credit_info = raw.get("credit_info", {})

        # Check if user specified a custom limit
        custom_limit = os.environ.get("OPENROUTER_DAILY_LIMIT")
        if custom_limit:
            try:
                limit = int(custom_limit)
            except ValueError:
                limit = self.FREE_DAILY_LIMIT
        else:
            # Default to 1000/day (paid tier assumption)
            # is_free_tier=true means NEVER paid, so 50/day
            is_free_tier = credit_info.get("is_free_tier", False)
            limit = self.FREE_DAILY_LIMIT_NO_CREDITS if is_free_tier else self.FREE_DAILY_LIMIT

        self._resolved_limit = limit

        pct_used = (request_count / limit * 100) if limit > 0 else 0.0
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        return [
            UsageRow(
                identifier=f"OpenRouter (daily, {limit} limit)",
                pct_used=pct_used,
                reset_at=tomorrow,
            )
        ]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Anchor when daily window has never started."""
        if any(r.is_exhausted for r in rows):
            return False
        return any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Fire when daily limit has reset and capacity is available."""
        daily_row = next((r for r in rows if "daily" in r.identifier), None)
        if daily_row and daily_row.pct_used == 0.0:
            self.send_ntfy(
                "OpenRouter Daily Reset",
                f"OpenRouter daily limit reset!\n\n{self._resolved_limit} requests available.",
                tags="white_check_mark,rocket",
            )
