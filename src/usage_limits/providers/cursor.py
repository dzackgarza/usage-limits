"""Cursor usage limits provider."""

from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TypedDict, cast

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class CursorPlanUsage(TypedDict):
    enabled: bool
    used: int
    limit: int
    remaining: int
    breakdown: CursorPlanBreakdown
    autoPercentUsed: int
    apiPercentUsed: int
    totalPercentUsed: int


class CursorPlanBreakdown(TypedDict):
    included: int
    bonus: int
    total: int


class CursorOnDemandUsage(TypedDict):
    enabled: bool
    used: int
    limit: int | None
    remaining: int | None


class CursorIndividualUsage(TypedDict):
    plan: CursorPlanUsage
    onDemand: CursorOnDemandUsage


class CursorUsageResponse(TypedDict):
    billingCycleStart: str
    billingCycleEnd: str
    membershipType: str
    limitType: str
    isUnlimited: bool
    autoModelSelectedDisplayMessage: str
    namedModelSelectedDisplayMessage: str
    individualUsage: CursorIndividualUsage
    teamUsage: dict[str, object]


class CursorProvider(UsageProvider):
    """Cursor usage checker (aggregate plan usage)."""

    slug = "cursor"
    name = "Cursor"
    state_dir = "cursor_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    USAGE_URL = "https://cursor.com/api/usage-summary"

    def __init__(self) -> None:
        super().__init__()
        self.state_db = (
            Path.home()
            / ".config"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )

    def provider_name(self) -> str:
        return "Cursor"

    def get_access_token(self) -> str:
        conn = sqlite3.connect(self.state_db)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM ItemTable WHERE key = 'cursorAuth/accessToken'"
        )
        row = cursor.fetchone()
        conn.close()
        token: str = row[0]
        return token

    def fetch_raw(self) -> CursorUsageResponse:
        access_token = self.get_access_token()

        # Build WorkosCursorSessionToken cookie
        # accessToken is a JWT, extract sub to get user_id
        jwt_payload = access_token.split(".")[1]
        jwt_payload += "=" * (4 - len(jwt_payload) % 4)
        decoded = json.loads(base64.b64decode(jwt_payload))
        sub = decoded["sub"]
        user_id = sub.split("|")[-1] if "|" in sub else sub

        cookie = f"WorkosCursorSessionToken={user_id}%3A%3A{access_token}"

        resp = requests.get(
            self.USAGE_URL,
            headers={
                "Accept": "application/json",
                "Cookie": cookie,
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return cast(CursorUsageResponse, resp.json())

    def to_rows(self, raw: CursorUsageResponse) -> list[UsageRow]:
        membership = raw["membershipType"]
        usage = raw["individualUsage"]
        rows: list[UsageRow] = []

        # Plan usage — always report even when limit is 0
        plan = usage["plan"]
        plan_limit = plan["limit"]
        plan_used = plan["used"]

        if isinstance(plan_limit, int) and plan_limit > 0:
            pct_used = (plan_used / plan_limit) * 100
        else:
            # For free plans with limit=0, use totalPercentUsed from the API
            pct_used = plan["totalPercentUsed"]

        billing_end = raw.get("billingCycleEnd")
        reset_at = None
        if billing_end:
            reset_at = datetime.fromisoformat(billing_end.replace("Z", "+00:00"))

        rows.append(
            UsageRow(
                identifier=f"Cursor ({membership} - Plan)",
                pct_used=pct_used,
                reset_at=reset_at,
            )
        )

        # On-demand usage (only when limit > 0)
        on_demand = usage["onDemand"]
        on_demand_limit = on_demand["limit"]
        on_demand_used = on_demand["used"]
        if isinstance(on_demand_limit, int) and on_demand_limit > 0:
            pct_used = (on_demand_used / on_demand_limit) * 100
            rows.append(
                UsageRow(
                    identifier=f"Cursor ({membership} - On Demand)",
                    pct_used=pct_used,
                    reset_at=None,
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
                "Cursor Window Open",
                "Cursor credits available!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str] | None:
        return None
