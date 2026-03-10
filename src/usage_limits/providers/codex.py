"""Codex usage limits provider."""

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

    def __init__(self) -> None:
        super().__init__()
        self.auth_file = Path.home() / ".codex" / "auth.json"

    def provider_name(self) -> str:
        return "Codex"

    def get_credentials(self) -> dict[str, Any]:
        """Load auth credentials from ~/.codex/auth.json."""
        if not self.auth_file.exists():
            return {}
        try:
            data = json.loads(self.auth_file.read_text())
            return data.get("tokens", {})  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            return {}

    def fetch_raw(self) -> dict[str, Any]:
        """Fetch usage from the WHAM API."""
        creds = self.get_credentials()
        if not creds:
            print("Error: Not logged in. Run 'codex login'", file=sys.stderr)
            sys.exit(1)
        token = creds.get("access_token")
        if not token:
            print("Error: No access token", file=sys.stderr)
            sys.exit(1)

        try:
            resp = requests.get(
                "https://chatgpt.com/backend-api/wham/usage",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            if resp.status_code == 401:
                print("Error: Authentication failed. Run 'codex login'", file=sys.stderr)
                sys.exit(1)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except requests.RequestException as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    def to_rows(self, raw: Any) -> list[UsageRow]:
        rate_limit = raw.get("rate_limit", {})
        primary = rate_limit.get("primary_window", {})
        secondary = rate_limit.get("secondary_window", {})

        rows: list[UsageRow] = [
            UsageRow(
                identifier="Codex (5h)",
                pct_used=primary.get("used_percent", 0.0),
                reset_at=_ts_to_dt(primary.get("reset_at")),
            ),
        ]
        if secondary:
            rows.append(
                UsageRow(
                    identifier="Codex (7d)",
                    pct_used=secondary.get("used_percent", 0.0),
                    reset_at=_ts_to_dt(secondary.get("reset_at")),
                )
            )
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
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)
