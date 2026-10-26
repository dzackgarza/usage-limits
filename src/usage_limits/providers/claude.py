"""Claude Code usage limits provider."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from typing import TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.auth.claude import claude_oauth_flow
from usage_limits.auth.store import CredentialStore, StoredCredential
from usage_limits.config import settings
from usage_limits.table import UsageRow


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
        self.store = CredentialStore()

    def provider_name(self) -> str:
        return "Claude"

    def get_credentials(self) -> StoredCredential:
        return self.store.get("claude", self.account_id)

    def _get_claude_bin(self) -> str:
        """Find the claude executable."""
        return shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")

    def _refresh(self, old_token: str) -> str:
        with self.store.lock("claude", self.account_id):
            credential = self.get_credentials()
            if credential["access_token"] != old_token:
                return credential["access_token"]
            refresh_token = credential["refresh_token"]
            assert refresh_token is not None
            result = claude_oauth_flow().refresh(refresh_token)
            credential["access_token"] = result["access_token"]
            credential["expires_at"] = result["expires_at"]
            if result["new_refresh_token"] is not None:
                credential["refresh_token"] = result["new_refresh_token"]
            self.store.save("claude", self.account_id, credential)
            return credential["access_token"]

    def fetch_raw(self) -> ClaudeUsageResponse:
        def _call(access_token: str) -> requests.Response:
            return requests.get(
                settings.claude.api_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "anthropic-beta": settings.claude.beta_header,
                },
                timeout=30,
            )

        creds = self.get_credentials()
        access_token = creds["access_token"]
        expires_at = creds["expires_at"]
        assert expires_at is not None
        if datetime.fromisoformat(expires_at) <= datetime.now(UTC):
            access_token = self._refresh(access_token)
        resp = _call(access_token)
        if resp.status_code == 401:
            resp = _call(self._refresh(access_token))
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
        claude_bin = self._get_claude_bin()
        return [
            claude_bin,
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
