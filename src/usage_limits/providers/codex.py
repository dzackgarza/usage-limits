"""Codex usage limits provider."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class CodexCredentials(TypedDict):
    access_token: str


class WhamWindow(TypedDict):
    used_percent: float
    reset_at: int | None


class WhamRateLimit(TypedDict):
    primary_window: WhamWindow
    secondary_window: WhamWindow | None


class WhamUsageResponse(TypedDict):
    rate_limit: WhamRateLimit


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

    def get_credentials(self) -> CodexCredentials:
        data: dict[str, Any] = json.loads(self.auth_file.read_text())
        return cast(CodexCredentials, data["tokens"])

    def fetch_raw(self) -> WhamUsageResponse:
        creds = self.get_credentials()
        resp = requests.get(
            "https://chatgpt.com/backend-api/wham/usage",
            headers={"Authorization": f"Bearer {creds['access_token']}"},
            timeout=30,
        )
        resp.raise_for_status()
        return cast(WhamUsageResponse, resp.json())

    def to_rows(self, raw: WhamUsageResponse) -> list[UsageRow]:
        rate_limit = raw["rate_limit"]
        primary = rate_limit["primary_window"]
        secondary = rate_limit["secondary_window"]

        rows: list[UsageRow] = [
            UsageRow(
                identifier="Codex (5h)",
                pct_used=primary["used_percent"],
                reset_at=_ts_to_dt(primary["reset_at"]),
            ),
        ]
        if secondary:
            rows.append(
                UsageRow(
                    identifier="Codex (7d)",
                    pct_used=secondary["used_percent"],
                    reset_at=_ts_to_dt(secondary["reset_at"]),
                )
            )
        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        if any(r.is_exhausted for r in rows):
            return False
        return any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
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
