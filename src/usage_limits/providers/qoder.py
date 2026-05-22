"""Qoder usage limits provider."""

from __future__ import annotations

import json
import sqlite3
from typing import TypedDict, cast

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class QoderQuotaBucket(TypedDict, total=False):
    used: float
    total: float
    remaining: float
    percentage: float
    unit: str


class QoderCreditUsage(TypedDict, total=False):
    userQuota: QoderQuotaBucket
    addOnQuota: QoderQuotaBucket
    totalUsagePercentage: float
    expiresAt: float
    plan_tier_name: str


class QoderUserInfo(TypedDict, total=False):
    email: str
    name: str
    id: str
    userTag: str


class QoderUserPlan(TypedDict, total=False):
    plan: str
    tier: str
    plan_tier_name: str


class QoderCredentials(TypedDict):
    user_info: QoderUserInfo
    user_plan: QoderUserPlan
    credit_usage: QoderCreditUsage


class QoderProvider(UsageProvider):
    """Qoder usage checker (credits, user quota, add-on quota)."""

    slug = "qoder"
    name = "Qoder"
    state_dir = "qoder_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    SECRET_USER_INFO_KEY = "secret://aicoding.auth.userInfo"
    SECRET_USER_PLAN_KEY = "secret://aicoding.auth.userPlan"
    SECRET_CREDIT_USAGE_KEY = "secret://aicoding.auth.creditUsage"

    def __init__(self) -> None:
        super().__init__()
        self.state_db = (
            __import__("pathlib").Path.home()
            / ".config"
            / "Qoder"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )

    def provider_name(self) -> str:
        return "Qoder"

    def get_credentials(self) -> QoderCredentials:
        conn = sqlite3.connect(self.state_db)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT key, value FROM ItemTable WHERE key IN (?, ?, ?)',
            [
                self.SECRET_USER_INFO_KEY,
                self.SECRET_USER_PLAN_KEY,
                self.SECRET_CREDIT_USAGE_KEY,
            ],
        )
        rows = cursor.fetchall()
        conn.close()

        data: dict[str, str] = {}
        for key, value in rows:
            data[key] = value

        user_info = json.loads(data[self.SECRET_USER_INFO_KEY])
        user_plan = json.loads(data[self.SECRET_USER_PLAN_KEY])
        credit_usage = json.loads(data[self.SECRET_CREDIT_USAGE_KEY])

        return {
            "user_info": cast(QoderUserInfo, user_info),
            "user_plan": cast(QoderUserPlan, user_plan),
            "credit_usage": cast(QoderCreditUsage, credit_usage),
        }

    def fetch_raw(self) -> QoderCredentials:
        return self.get_credentials()

    def to_rows(self, raw: QoderCredentials) -> list[UsageRow]:
        credit_usage = raw["credit_usage"]
        user_info = raw["user_info"]
        user_plan = raw["user_plan"]

        plan_name = (
            user_plan.get("plan_tier_name")
            or user_plan.get("plan")
            or user_info.get("userTag")
            or "Unknown"
        )

        rows: list[UsageRow] = []

        # User quota
        user_quota = credit_usage["userQuota"]
        used = user_quota["used"]
        total = user_quota["total"]
        if total > 0:
            pct_used = (used / total) * 100
        else:
            pct_used = user_quota.get("percentage", 0.0)

        email = user_info.get("email", "unknown")
        rows.append(
            UsageRow(
                identifier=f"Qoder ({plan_name} - {email})",
                pct_used=pct_used,
                reset_at=None,
            )
        )

        # Add-on quota (if present)
        add_on_quota = credit_usage.get("addOnQuota")
        if add_on_quota:
            addon_used = add_on_quota.get("used", 0)
            addon_total = add_on_quota.get("total", 0)
            if addon_total > 0:
                addon_pct = (addon_used / addon_total) * 100
            else:
                addon_pct = add_on_quota.get("percentage", 0.0)

            rows.append(
                UsageRow(
                    identifier=f"Qoder (Add-on - {email})",
                    pct_used=addon_pct,
                    reset_at=None,
                )
            )

        # Total usage percentage
        total_pct = credit_usage.get("totalUsagePercentage")
        if total_pct is not None:
            rows.append(
                UsageRow(
                    identifier=f"Qoder (Total - {email})",
                    pct_used=total_pct,
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
                "Qoder Window Open",
                "Qoder credits available!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str] | None:
        return None
