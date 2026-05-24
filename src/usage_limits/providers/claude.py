"""Claude Code usage limits provider."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class ClaudeCredentials(TypedDict):
    accessToken: str
    scopes: list[str]


class ClaudeUsageWindow(TypedDict):
    utilization: float
    resets_at: str | None


class ClaudeUsageResponse(TypedDict):
    five_hour: ClaudeUsageWindow
    seven_day: ClaudeUsageWindow


class ClaudeProvider(UsageProvider):
    """Claude Code usage checker (5-hour and 7-day OAuth-gated windows)."""

    slug = "claude"
    name = "Claude Code"
    state_dir = "claude_usage"
    cache_ttl_seconds = 300
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self) -> None:
        super().__init__()
        self.cred_file = Path.home() / ".claude" / ".credentials.json"

    def provider_name(self) -> str:
        return "Claude"

    def get_credentials(self) -> ClaudeCredentials:
        data: dict[str, Any] = json.loads(self.cred_file.read_text())
        return cast(ClaudeCredentials, data["claudeAiOauth"])

    def _reset_rate_limit(self) -> bool:
        """Run a minimal Claude CLI turn to reset the rate-limit window.

        Runs in a temp directory with empty setting sources to minimize
        token overhead. Only attempts once.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    "claude",
                    "--setting-sources",
                    "",
                    "-p",
                    "Say hello and nothing more, do not take any other actions",
                ],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return result.returncode == 0

    def fetch_raw(self) -> ClaudeUsageResponse:
        creds = self.get_credentials()

        def _call() -> requests.Response:
            return requests.get(
                "https://api.anthropic.com/api/oauth/usage",
                headers={
                    "Authorization": f"Bearer {creds['accessToken']}",
                    "anthropic-beta": "oauth-2025-04-20",
                },
                timeout=30,
            )

        resp = _call()
        if resp.status_code == 429:
            self._reset_rate_limit()
            resp = _call()
        resp.raise_for_status()
        return cast(ClaudeUsageResponse, resp.json())

    def to_rows(self, raw: ClaudeUsageResponse) -> list[UsageRow]:
        five_hour = raw["five_hour"]
        seven_day = raw["seven_day"]
        return [
            UsageRow(
                identifier="Claude (5h)",
                pct_used=five_hour["utilization"],
                reset_at=_parse_dt(five_hour["resets_at"]),
            ),
            UsageRow(
                identifier="Claude (7d)",
                pct_used=seven_day["utilization"],
                reset_at=_parse_dt(seven_day["resets_at"]),
            ),
        ]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        if any(r.is_exhausted for r in rows):
            return False
        return any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
        if self.should_anchor(rows):
            self.send_ntfy(
                "Claude Window Open",
                "Claude Code 5h window open!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str]:
        return ["claude", "--setting-sources", "", "Say hello and do nothing else"]


def _parse_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
