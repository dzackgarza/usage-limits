"""Claude Code usage limits provider."""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import UTC, datetime
from typing import Any, TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.config import resolve_path, settings
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


class ClaudeProvider(ProviderAccount):
    """Claude Code usage checker (5-hour and 7-day OAuth-gated windows)."""

    slug = "claude"
    name = "Claude Code"
    state_dir = "claude_usage"
    cache_ttl_seconds = 300  # default; override in config.ntfy.cache_ttl_seconds

    def __init__(self) -> None:
        super().__init__()
        self.cred_file = resolve_path(settings.paths.claude_credentials)

    def provider_name(self) -> str:
        return "Claude"

    def get_credentials(self) -> ClaudeCredentials:
        data: dict[str, Any] = json.loads(self.cred_file.read_text())
        return cast(ClaudeCredentials, data["claudeAiOauth"])

    def _wake_cli(self) -> bool:
        """Run a minimal Claude CLI turn to refresh tokens or reset rate limit.

        Runs in a temp directory with empty setting sources to minimize
        token overhead. Only attempts once.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    "claude",
                    "--safe-mode",
                    "--tools",
                    "",
                    "--no-session-persistence",
                    "--system-prompt",
                    "You are a minimal token refresher. Reply only with 'ok'.",
                    "-p",
                    "ok",
                ],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0

    def fetch_raw(self) -> ClaudeUsageResponse:
        def _call(creds: ClaudeCredentials) -> requests.Response:
            return requests.get(
                settings.claude.api_url,
                headers={
                    "Authorization": f"Bearer {creds['accessToken']}",
                    "anthropic-beta": settings.claude.beta_header,
                },
                timeout=30,
            )

        creds = self.get_credentials()
        resp = _call(creds)
        if resp.status_code in (401, 429):
            self._wake_cli()
            creds = self.get_credentials()
            resp = _call(creds)
        resp.raise_for_status()
        return cast(ClaudeUsageResponse, resp.json())

    def to_rows(self, raw: ClaudeUsageResponse) -> list[UsageRow]:
        five_hour = raw["five_hour"]
        seven_day = raw["seven_day"]
        return [
            UsageRow(
                identifier="Claude (5h)",
                pct_used=round(five_hour["utilization"]),
                reset_at=_parse_dt(five_hour["resets_at"]),
            ),
            UsageRow(
                identifier="Claude (7d)",
                pct_used=round(seven_day["utilization"]),
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
        return [
            "claude",
            "--safe-mode",
            "--tools",
            "",
            "--no-session-persistence",
            "--system-prompt",
            "You are a minimal token refresher. Reply only with 'ok'.",
            "-p",
            "ok",
        ]


def _parse_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
