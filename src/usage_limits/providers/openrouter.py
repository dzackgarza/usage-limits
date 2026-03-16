"""OpenRouter usage limits provider.

Fetches the OpenRouter key details from the API to determine the daily
request limits for free models.

Known constraints:
- Free tier: 50 req/day if credits were never purchased; 1000 req/day otherwise.
- Daily limit resets at UTC midnight.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class OpenRouterProvider(UsageProvider):
    """OpenRouter daily request quota tracker."""

    slug = "openrouter"
    name = "OpenRouter"
    state_dir = "openrouter_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    FREE_DAILY_LIMIT = 1000  # 1000/day if credits ever purchased; 50/day if never paid
    FREE_DAILY_LIMIT_NO_CREDITS = 50

    def provider_name(self) -> str:
        return "OpenRouter"

    def fetch_raw(self) -> dict[str, Any]:
        """Fetch OpenRouter key details from the API and today's request count.

        Uses OPENROUTER_API_KEY if present, otherwise reads from a config file.
        """
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            config_file = Path.home() / ".config" / "usage-limits" / "openrouter.json"
            if config_file.exists():
                try:
                    config = json.loads(config_file.read_text())
                    api_key = config.get("api_key")
                except (json.JSONDecodeError, OSError):
                    pass

        key_info: dict[str, Any] = {}
        if not api_key:
            print(
                "Warning: No OpenRouter API key found (OPENROUTER_API_KEY)."
                " Using default free tier limits.",
                file=sys.stderr,
            )
        else:
            try:
                response = requests.get(
                    "https://openrouter.ai/api/v1/key",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10,
                )
                response.raise_for_status()
                key_info = response.json().get("data", {})
            except requests.RequestException as e:
                print(f"Warning: Failed to fetch OpenRouter key info: {e}", file=sys.stderr)

        # OpenRouter does not emit OTLP events, so request counts are not
        # available locally. count=0 means pct_used reflects tier only.
        return {"key_info": key_info, "count": 0}

    def to_rows(self, raw: Any) -> list[UsageRow]:
        key_info = raw.get("key_info", {})
        request_count = raw.get("count", 0)

        # is_free_tier is boolean; if true, the user has NEVER paid for credits
        is_free_tier = key_info.get("is_free_tier", True)
        limit = self.FREE_DAILY_LIMIT_NO_CREDITS if is_free_tier else self.FREE_DAILY_LIMIT

        pct_used = (request_count / limit * 100) if limit > 0 else 0.0
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
