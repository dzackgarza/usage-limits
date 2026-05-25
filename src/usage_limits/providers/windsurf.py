"""Windsurf usage limits provider."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.table import UsageRow


class WindsurfCredentials(TypedDict):
    api_key: str


class WindsurfPlanInfo(TypedDict):
    planName: str
    monthlyPromptCredits: int
    monthlyFlowCredits: int


class WindsurfPlanStatus(TypedDict):
    planInfo: WindsurfPlanInfo
    availablePromptCredits: int
    availableFlowCredits: int
    dailyQuotaRemainingPercent: int
    weeklyQuotaRemainingPercent: int
    dailyQuotaResetAtUnix: int | str
    weeklyQuotaResetAtUnix: int | str


class WindsurfUserStatus(TypedDict):
    name: str
    email: str
    planStatus: WindsurfPlanStatus


class WindsurfUserStatusResponse(TypedDict):
    userStatus: WindsurfUserStatus


class WindsurfProvider(ProviderAccount):
    """Windsurf usage checker (prompt credits, flow credits, daily/weekly quotas)."""

    slug = "windsurf"
    name = "Windsurf"
    state_dir = "windsurf_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self) -> None:
        super().__init__()
        self.state_db = (
            Path.home() / ".config" / "Windsurf" / "User" / "globalStorage" / "state.vscdb"
        )

    def provider_name(self) -> str:
        return "Windsurf"

    def get_credentials(self) -> WindsurfCredentials:
        conn = sqlite3.connect(self.state_db)
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM ItemTable WHERE key = "windsurfAuthStatus"')
        row = cursor.fetchone()
        conn.close()

        auth_status = json.loads(row[0])
        api_key = auth_status["apiKey"]
        return {"api_key": api_key}

    def fetch_raw(self) -> WindsurfUserStatusResponse:
        creds = self.get_credentials()
        api_key = creds["api_key"]

        url = "https://windsurf.com/_backend/exa.seat_management_pb.SeatManagementService/GetUserStatus"
        body = {
            "metadata": {
                "apiKey": api_key,
                "ideName": "Windsurf",
                "ideVersion": "1.0.0",
                "extensionName": "codeium.windsurf",
                "extensionVersion": "1.0.0",
                "locale": "en-US",
                "os": "linux",
                "disableTelemetry": False,
                "sessionId": "usage-limits",
                "requestId": str(int(datetime.now(UTC).timestamp())),
            }
        }

        resp = requests.post(
            url,
            json=body,
            headers={
                "User-Agent": "usage-limits",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return cast(WindsurfUserStatusResponse, resp.json())

    def to_rows(self, raw: WindsurfUserStatusResponse) -> list[UsageRow]:
        plan_status = raw["userStatus"]["planStatus"]

        rows: list[UsageRow] = []

        # Daily quota
        daily_remaining = plan_status["dailyQuotaRemainingPercent"]
        daily_used = 100 - daily_remaining
        daily_reset = datetime.fromtimestamp(int(plan_status["dailyQuotaResetAtUnix"]), tz=UTC)
        rows.append(
            UsageRow(
                identifier="Windsurf (24h)",
                pct_used=float(daily_used),
                reset_at=daily_reset,
            )
        )

        # Weekly quota
        weekly_remaining = plan_status["weeklyQuotaRemainingPercent"]
        weekly_used = 100 - weekly_remaining
        weekly_reset = datetime.fromtimestamp(int(plan_status["weeklyQuotaResetAtUnix"]), tz=UTC)
        rows.append(
            UsageRow(
                identifier="Windsurf (7d)",
                pct_used=float(weekly_used),
                reset_at=weekly_reset,
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
                "Windsurf Window Open",
                "Windsurf credits available!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str] | None:
        return None
