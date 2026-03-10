"""Claude Code usage limits provider."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class ClaudeProvider(UsageProvider):
    """Claude Code usage checker (5-hour and 7-day OAuth-gated windows)."""

    slug = "claude"
    name = "Claude Code"
    state_dir = "claude_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self) -> None:
        super().__init__()
        self.cred_file = Path.home() / ".claude" / ".credentials.json"

    def provider_name(self) -> str:
        return "Claude"

    def get_credentials(self) -> dict[str, Any]:
        """Load OAuth credentials from ~/.claude/.credentials.json."""
        if not self.cred_file.exists():
            return {}
        try:
            data = json.loads(self.cred_file.read_text())
            return data.get("claudeAiOauth", {})  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            return {}

    def fetch_raw(self) -> dict[str, Any]:
        """Fetch usage from the Claude OAuth API."""
        creds = self.get_credentials()
        if not creds:
            print("Error: Not logged in. Run 'claude login'", file=sys.stderr)
            sys.exit(1)
        token = creds.get("accessToken")
        if not token:
            print("Error: No access token", file=sys.stderr)
            sys.exit(1)
        if "user:profile" not in creds.get("scopes", []):
            print("Error: Token missing 'user:profile' scope", file=sys.stderr)
            sys.exit(1)

        try:
            return self._fetch_usage(token)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                print("Warning: Token expired (401). Re-initializing auth...", file=sys.stderr)
                subprocess.run(["timeout", "5", "claude"], capture_output=True)
                creds = self.get_credentials()
                token = creds.get("accessToken") if creds else None
                if not token:
                    print("Error: No access token after auth re-init", file=sys.stderr)
                    sys.exit(1)
                return self._fetch_usage(token)
            raise

    def _fetch_usage(self, token: str) -> dict[str, Any]:
        resp = requests.get(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    def to_rows(self, raw: Any) -> list[UsageRow]:
        rows: list[UsageRow] = []

        five_hour = raw.get("five_hour", {})
        rows.append(
            UsageRow(
                identifier="Claude (5h)",
                pct_used=five_hour.get("utilization", 0.0),
                reset_at=_parse_dt(five_hour.get("resets_at")),
            )
        )

        seven_day = raw.get("seven_day", {})
        rows.append(
            UsageRow(
                identifier="Claude (7d)",
                pct_used=seven_day.get("utilization", 0.0),
                reset_at=_parse_dt(seven_day.get("resets_at")),
            )
        )

        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Anchor when any window has never started and none are exhausted.

        | 5h          | 7d          | Anchor? |
        |-------------|-------------|---------|
        | no reset    | no reset    | Yes     |
        | no reset    | active      | Yes     |
        | no reset    | exhausted   | No      |
        | active      | no reset    | Yes     |
        | active      | active      | No      |
        | active      | exhausted   | No      |
        | exhausted   | any         | No      |
        """
        if any(r.is_exhausted for r in rows):
            return False
        return any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Fire when the 5h window is fresh and the 7d window isn't exhausted."""
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
