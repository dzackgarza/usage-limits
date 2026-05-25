"""Qoder usage limits provider."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.table import UsageRow

QODER_OPENAPI_BASE_URL = "https://openapi.qoder.sh"
CREDIT_USAGE_PATH = "/api/v2/quota/usage"

COCKPIT_ACCOUNTS_DIR = Path.home() / ".antigravity_cockpit" / "qoder_accounts"


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


class QoderCredentials(TypedDict):
    token: str
    email: str
    user_id: str
    plan_type: str
    credit_usage: QoderCreditUsage


class QoderProvider(ProviderAccount):
    """Qoder usage checker (credits quota via OpenAPI)."""

    slug = "qoder"
    name = "Qoder"
    state_dir = "qoder_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def provider_name(self) -> str:
        return "Qoder"

    def get_access_token(self) -> str:
        """Read the access token from the cockpit-tools Qoder account store."""
        json_files = sorted(COCKPIT_ACCOUNTS_DIR.glob("qoder_uid_*.json"))
        account_file = json_files[0]
        with open(account_file) as f:
            account = json.load(f)
        token = account["auth_user_info_raw"]["token"]
        assert isinstance(token, str)
        return token

    def get_account_meta(self) -> dict[str, str]:
        """Read account metadata from the cockpit-tools Qoder account store."""
        json_files = sorted(COCKPIT_ACCOUNTS_DIR.glob("qoder_uid_*.json"))
        account_file = json_files[0]
        with open(account_file) as f:
            account = json.load(f)
        return {
            "email": account["email"],
            "user_id": account["user_id"],
            "plan_type": account["plan_type"],
        }

    def fetch_raw(self) -> QoderCredentials:
        token = self.get_access_token()
        meta = self.get_account_meta()

        usage_url = f"{QODER_OPENAPI_BASE_URL}{CREDIT_USAGE_PATH}"
        resp = requests.get(
            usage_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        credit_usage = cast(QoderCreditUsage, resp.json())

        return {
            "token": token,
            "email": meta["email"],
            "user_id": meta["user_id"],
            "plan_type": meta["plan_type"],
            "credit_usage": credit_usage,
        }

    def to_rows(self, raw: QoderCredentials) -> list[UsageRow]:
        credit_usage = raw["credit_usage"]
        email = raw["email"]
        plan_type = raw["plan_type"]

        rows: list[UsageRow] = []

        # User quota — only produce a row when the bucket has meaningful data
        user_quota = credit_usage["userQuota"]
        used = user_quota["used"]
        total = user_quota["total"]
        if isinstance(total, (int, float)) and total > 0:
            pct_used = (used / total) * 100
            rows.append(
                UsageRow(
                    identifier=f"Qoder ({plan_type} - {email})",
                    pct_used=pct_used,
                    reset_at=None,
                )
            )

        # Add-on quota (if present)
        add_on_quota = credit_usage.get("addOnQuota")
        if add_on_quota:
            addon_used = add_on_quota["used"]
            addon_total = add_on_quota["total"]
            if isinstance(addon_total, (int, float)) and addon_total > 0:
                addon_pct = (addon_used / addon_total) * 100
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
