"""Codex usage limits provider.

Aligned with OpenChamber implementation:
- Auth source: ~/.local/share/opencode/auth.json
- API: https://chatgpt.com/backend-api/wham/usage
- Supports accountId for team accounts
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class CodexProvider(UsageProvider):
    """Codex CLI usage checker (5-hour and 7-day WHAM windows)."""

    slug = "codex"
    name = "Codex"
    state_dir = "codex_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"
    API_ENDPOINT = "https://chatgpt.com/backend-api/wham/usage"

    def __init__(self) -> None:
        super().__init__()
        self.auth_file = Path.home() / ".local" / "share" / "opencode" / "auth.json"

    def provider_name(self) -> str:
        return "Codex"

    def get_credentials(self) -> dict[str, Any]:
        """Load auth credentials from ~/.local/share/opencode/auth.json.

        Expected structure:
        {
          "openai": {
            "type": "oauth",
            "access": "<access_token>",
            "refresh": "<refresh_token>",
            "expires": <timestamp>,
            "accountId": "<optional_team_id>"
          }
        }
        """
        if not self.auth_file.exists():
            return {}
        try:
            data = json.loads(self.auth_file.read_text())
            # Check for openai, codex, or chatgpt keys (OpenChamber aliases)
            for key in ["openai", "codex", "chatgpt"]:
                if key in data:
                    entry = data[key]
                    if isinstance(entry, dict):
                        return entry
            return {}
        except (json.JSONDecodeError, OSError):
            return {}

    def fetch_raw(self) -> dict[str, Any]:
        """Fetch usage from the WHAM API."""
        creds = self.get_credentials()
        if not creds:
            print("Error: Not logged in. Run 'codex login'", file=sys.stderr)
            sys.exit(1)

        access_token = creds.get("access") or creds.get("token")
        if not access_token:
            print("Error: No access token", file=sys.stderr)
            sys.exit(1)

        try:
            return self._fetch_usage(access_token, creds.get("accountId"))
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                print(
                    "Error: Session expired — please re-authenticate with OpenAI", file=sys.stderr
                )
                sys.exit(1)
            raise

    def _fetch_usage(self, token: str, account_id: str | None = None) -> dict[str, Any]:
        """Fetch usage data from WHAM API."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id

        resp = requests.get(
            self.API_ENDPOINT,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    def to_rows(self, raw: Any) -> list[UsageRow]:
        """Convert WHAM API response to usage rows.

        Response structure:
        {
          "rate_limit": {
            "primary_window": {
              "used_percent": 45,
              "limit_window_seconds": 18000,
              "reset_at": 1773934845
            },
            "secondary_window": {...}
          },
          "credits": {
            "balance": 25.50,
            "unlimited": false
          }
        }
        """
        rate_limit = raw.get("rate_limit", {})
        primary = rate_limit.get("primary_window", {})
        secondary = rate_limit.get("secondary_window", {})
        credits = raw.get("credits", {})

        rows: list[UsageRow] = []

        if primary:
            rows.append(
                UsageRow(
                    identifier="Codex (5h)",
                    pct_used=float(primary.get("used_percent", 0.0)),
                    reset_at=_ts_to_dt(primary.get("reset_at")),
                )
            )

        if secondary:
            rows.append(
                UsageRow(
                    identifier="Codex (weekly)",
                    pct_used=float(secondary.get("used_percent", 0.0)),
                    reset_at=_ts_to_dt(secondary.get("reset_at")),
                )
            )

        # Note: credits field contains paid API balance, not usage limits.
        # We don't display this as it's not a quota/limit metric.
        # if credits: ...  # Removed per user feedback

        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Anchor when any window has never started and none are exhausted."""
        if any(r.is_exhausted for r in rows):
            return False
        return any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Fire when the 5h window is fresh and the 7d window isn't exhausted."""
        if self.should_anchor(rows):
            self.send_ntfy(
                "Codex Window Open",
                "Codex 5h window open!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str]:
        return ["codex", "exec", "-c", "project_doc_max_bytes=0", "Say hello and do nothing else"]


def _ts_to_dt(ts: int | None) -> datetime | None:
    """Convert Unix timestamp to datetime."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC)
    except (ValueError, TypeError, OSError):
        return None
