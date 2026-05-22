"""Kiro usage limits provider."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class KiroCredentials(TypedDict):
    access_token: str
    refresh_token: str
    provider: str
    profile_arn: str


class KiroUsageBreakdown(TypedDict):
    currency: str
    currentUsage: float
    currentUsageWithPrecision: float
    displayName: str
    displayNamePlural: str
    freeTrialInfo: FreeTrialInfo | None
    nextDateReset: float
    resourceType: str
    unit: str
    usageLimit: float
    usageLimitWithPrecision: float


class FreeTrialInfo(TypedDict):
    currentUsage: float
    currentUsageWithPrecision: float
    freeTrialExpiry: float
    freeTrialStatus: str
    usageLimit: float
    usageLimitWithPrecision: float


class KiroUsageResponse(TypedDict):
    usageBreakdownList: list[KiroUsageBreakdown]
    subscriptionInfo: SubscriptionInfo


class SubscriptionInfo(TypedDict):
    subscriptionTitle: str
    type: str


class KiroProvider(UsageProvider):
    """Kiro usage checker (credits and bonus/free trial)."""

    slug = "kiro"
    name = "Kiro"
    state_dir = "kiro_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self) -> None:
        super().__init__()
        self.db_path = Path.home() / ".local" / "share" / "kiro-cli" / "data.sqlite3"

    def provider_name(self) -> str:
        return "Kiro"

    def get_credentials(self) -> KiroCredentials:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM auth_kv WHERE key = 'kirocli:social:token'")
        row = cursor.fetchone()
        conn.close()

        if row is None:
            raise FileNotFoundError(f"No credentials found in {self.db_path}")

        data: dict[str, Any] = json.loads(row[0])
        return cast(KiroCredentials, data)

    def fetch_raw(self) -> KiroUsageResponse:
        creds = self.get_credentials()
        resp = requests.get(
            "https://q.us-east-1.amazonaws.com/getUsageLimits",
            params={
                "origin": "AI_EDITOR",
                "profileArn": creds["profile_arn"],
                "resourceType": "AGENTIC_REQUEST",
            },
            headers={"Authorization": f"Bearer {creds['access_token']}"},
            timeout=30,
        )
        resp.raise_for_status()
        return cast(KiroUsageResponse, resp.json())

    def to_rows(self, raw: KiroUsageResponse) -> list[UsageRow]:
        breakdown_list = raw["usageBreakdownList"]
        if not breakdown_list:
            return []

        rows: list[UsageRow] = []
        for breakdown in breakdown_list:
            if breakdown["resourceType"] != "CREDIT":
                continue

            # Main credits
            total = breakdown["usageLimit"]
            used = breakdown["currentUsage"]
            pct_used = (used / total * 100) if total > 0 else 0.0
            reset_at = datetime.fromtimestamp(breakdown["nextDateReset"], tz=UTC)

            rows.append(
                UsageRow(
                    identifier=f"Kiro ({breakdown['displayName']})",
                    pct_used=pct_used,
                    reset_at=reset_at,
                )
            )

            # Bonus/free trial
            free_trial = breakdown.get("freeTrialInfo")
            if free_trial and free_trial["freeTrialStatus"] != "EXPIRED":
                bonus_total = free_trial["usageLimit"]
                bonus_used = free_trial["currentUsage"]
                bonus_pct = (bonus_used / bonus_total * 100) if bonus_total > 0 else 0.0
                bonus_reset = datetime.fromtimestamp(
                    free_trial["freeTrialExpiry"], tz=UTC
                )

                rows.append(
                    UsageRow(
                        identifier=f"Kiro Bonus ({breakdown['displayName']})",
                        pct_used=bonus_pct,
                        reset_at=bonus_reset,
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
                "Kiro Window Open",
                "Kiro credits available!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str] | None:
        return None
