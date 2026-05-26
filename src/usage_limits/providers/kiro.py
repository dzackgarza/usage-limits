"""Kiro usage limits provider."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any, TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.config import resolve_path
from usage_limits.table import UsageRow

# Default refresh endpoint — override via config
_KIRO_REFRESH_ENDPOINT = "https://prod.us-east-1.auth.desktop.kiro.dev/refreshToken"


class KiroCredentials(TypedDict):
    access_token: str
    refresh_token: str
    provider: str
    profile_arn: str | None


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


class KiroProvider(ProviderAccount):
    """Kiro usage checker (credits and bonus/free trial)."""

    slug = "kiro"
    name = "Kiro"
    state_dir = "kiro_usage"

    def __init__(self) -> None:
        super().__init__()
        from usage_limits.config import settings as _cfg

        self.db_path = resolve_path(_cfg.paths.kiro_db)

    def provider_name(self) -> str:
        return "Kiro"

    def _read_db(self) -> dict[str, Any]:
        """Read raw token data from the kiro-cli SQLite database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM auth_kv WHERE key = 'kirocli:social:token'")
        row = cursor.fetchone()
        conn.close()

        if row is None:
            raise FileNotFoundError(f"No credentials found in {self.db_path}")

        data: dict[str, Any] = json.loads(row[0])
        return data

    def _get_profile_arn(self) -> str:
        """Get profileArn from the state table in the kiro-cli database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM state WHERE key = 'api.codewhisperer.profile'")
        row = cursor.fetchone()
        conn.close()

        if row is None:
            raise FileNotFoundError("No profile found in kiro-cli state table")

        profile: dict[str, Any] = json.loads(row[0])
        arn: str = profile["arn"]
        return arn

    def _refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token using the refresh_token endpoint."""
        from usage_limits.config import settings as _cfg

        resp = requests.post(
            _cfg.kiro.refresh_endpoint,
            json={"refreshToken": refresh_token},
            timeout=30,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    def get_credentials(self) -> KiroCredentials:
        data = self._read_db()

        access_token = data["access_token"]
        refresh_token = data["refresh_token"]
        provider = data["provider"]

        # Check if token is expired
        expires_at_str = data.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            now = datetime.now(tz=UTC)
            if now >= expires_at:
                # Token expired, refresh it
                new_token_data = self._refresh_token(refresh_token)
                access_token = new_token_data["accessToken"]

                # Update the database with new token
                data["access_token"] = access_token
                data["expires_at"] = new_token_data.get("expiresAt", expires_at_str)
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE auth_kv SET value = ? WHERE key = 'kirocli:social:token'",
                    [json.dumps(data)],
                )
                conn.commit()
                conn.close()

        # profileArn is None in the token JSON, read from state table
        profile_arn = self._get_profile_arn()

        return cast(
            KiroCredentials,
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "provider": provider,
                "profile_arn": profile_arn,
            },
        )

    def fetch_raw(self) -> KiroUsageResponse:
        from usage_limits.config import settings as _cfg

        creds = self.get_credentials()
        resp = requests.get(
            _cfg.kiro.usage_endpoint,
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
                bonus_reset = datetime.fromtimestamp(free_trial["freeTrialExpiry"], tz=UTC)

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
