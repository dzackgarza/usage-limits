"""Qwen usage limits provider.

Qwen Code free tier: 1000 requests/day (resets at UTC midnight).
Usage is tracked via local OpenAI logging files in ~/qwen-logs/.

Setup:
1. Enable OpenAI logging in ~/.qwen/settings.json:
   {
     "model": {
       "enableOpenAILogging": true,
       "openAILoggingDir": "~/qwen-logs"
     }
   }
2. Logs will be created at ~/qwen-logs/openai-*.json
"""

from __future__ import annotations

import glob
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class QwenProvider(UsageProvider):
    """Qwen Code usage checker.

    Counts today's requests by reading local log files created by the OpenAI
    logging feature of the Qwen Code extension.
    """

    slug = "qwen"
    name = "Qwen Code"
    state_dir = "qwen_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    FREE_DAILY_LIMIT = 1000

    def __init__(self) -> None:
        super().__init__()
        self.log_dir = Path.home() / "qwen-logs"

    def provider_name(self) -> str:
        return "Qwen"

    def fetch_raw(self) -> dict[str, Any]:
        """Count today's requests from local log files.

        Each log file represents one API request. Files are named with
        timestamps: openai-YYYY-MM-DDTHH-MM-SS.mmmZ-*.json
        """
        if not self.log_dir.exists():
            print(
                f"Error: Log directory {self.log_dir} does not exist.\n"
                "\nSetup:\n"
                "1. Enable OpenAI logging in ~/.qwen/settings.json:\n"
                '   {\n     "model": {\n'
                '       "enableOpenAILogging": true,\n'
                '       "openAILoggingDir": "~/qwen-logs"\n'
                "     }\n   }",
                file=sys.stderr,
            )
            sys.exit(1)

        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = today_start.strftime("%Y-%m-%d")
        pattern = str(self.log_dir / f"openai-{today_str}T*.json")
        return {"count": len(glob.glob(pattern))}

    def to_rows(self, raw: Any) -> list[UsageRow]:
        request_count = raw.get("count", 0)
        pct_used = (
            (request_count / self.FREE_DAILY_LIMIT * 100) if self.FREE_DAILY_LIMIT > 0 else 0.0
        )
        now = datetime.now(UTC)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return [UsageRow(identifier="Qwen (daily)", pct_used=pct_used, reset_at=tomorrow)]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Qwen daily limit resets automatically at UTC midnight — no anchoring."""
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Fire when daily limit is fresh (0 requests used)."""
        daily_row = next((r for r in rows if "daily" in r.identifier), None)
        if daily_row and daily_row.pct_used == 0:
            self.send_ntfy(
                "Qwen Daily Reset",
                f"Qwen Code daily limit reset!\n\n{self.FREE_DAILY_LIMIT} requests available.",
                tags="white_check_mark,rocket",
            )
