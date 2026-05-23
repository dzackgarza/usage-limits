"""GitHub Copilot usage limits provider."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import TypedDict, cast

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class CopilotQuotaSnapshot(TypedDict):
    overage_count: int
    overage_permitted: bool
    percent_remaining: float
    quota_id: str
    quota_remaining: float
    unlimited: bool
    timestamp_utc: str
    has_quota: bool
    quota_reset_at: int
    token_based_billing: bool
    remaining: int
    entitlement: int


class CopilotEndpoints(TypedDict):
    api: str
    origin_tracker: str
    proxy: str
    telemetry: str


class CopilotUserResponse(TypedDict):
    login: str
    copilot_plan: str
    access_type_sku: str
    quota_reset_date: str
    quota_reset_date_utc: str
    quota_snapshots: dict[str, CopilotQuotaSnapshot]
    endpoints: CopilotEndpoints


class CopilotProvider(UsageProvider):
    """GitHub Copilot usage checker (premium interactions, chat, completions)."""

    slug = "copilot"
    name = "GitHub Copilot"
    state_dir = "copilot_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def provider_name(self) -> str:
        return "GitHub Copilot"

    def get_token(self) -> str:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        result.check_returncode()
        return result.stdout.strip()

    def fetch_raw(self) -> CopilotUserResponse:
        token = self.get_token()
        resp = requests.get(
            "https://api.github.com/copilot_internal/user",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/json",
                "Editor-Version": "vscode/1.100.0",
                "Editor-Plugin-Version": "copilot-chat/0.25.0",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return cast(CopilotUserResponse, resp.json())

    def to_rows(self, raw: CopilotUserResponse) -> list[UsageRow]:
        snapshots = raw["quota_snapshots"]
        quota_reset_dt = datetime.fromisoformat(
            raw["quota_reset_date_utc"].replace("Z", "+00:00")
        ).astimezone(UTC)

        rows: list[UsageRow] = []

        for quota_id, snapshot in snapshots.items():
            pct_used = 0.0 if snapshot["unlimited"] else 100.0 - snapshot["percent_remaining"]

            label = quota_id.replace("_", " ").title()
            rows.append(
                UsageRow(
                    identifier=f"Copilot ({label})",
                    pct_used=pct_used,
                    reset_at=quota_reset_dt,
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
                "Copilot Window Open",
                "Copilot credits available!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str] | None:
        return None
