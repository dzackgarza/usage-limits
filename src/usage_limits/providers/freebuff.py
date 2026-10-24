"""Freebuff usage limits provider."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast

import requests

from usage_limits.auth.session import configure_session_bus
from usage_limits.base import ProviderAccount
from usage_limits.config import resolve_path, settings
from usage_limits.table import UsageRow


class FreebuffCredentials(TypedDict):
    id: str
    name: str
    email: str
    authToken: str
    fingerprintId: str
    fingerprintHash: str


class FreebuffProfile(TypedDict):
    id: str
    name: str
    email: str
    fingerprintId: str
    fingerprintHash: str
    authToken: NotRequired[str]
    tokenStore: NotRequired[Literal["keychain"]]


class FreebuffCredentialFile(TypedDict):
    default: FreebuffProfile


class RateLimitDetail(TypedDict, total=False):
    model: str
    limit: int
    period: str
    resetTimeZone: str
    resetAt: str
    windowHours: int
    recentCount: int


class FreebuffSessionRaw(TypedDict, total=False):
    status: str
    accessTier: str
    instanceId: str | None
    model: str | None
    admittedAt: str | None
    expiresAt: str | None
    remainingMs: int | None
    rateLimit: RateLimitDetail | None
    rateLimitsByModel: dict[str, RateLimitDetail] | None


class BalanceBreakdown(TypedDict):
    free: float
    referral: float
    referral_legacy: float
    subscription: float
    purchase: float
    admin: float
    organization: float
    ad: float


class FreebuffUsageRaw(TypedDict):
    type: str
    usage: float
    remainingBalance: float
    balanceBreakdown: BalanceBreakdown
    next_quota_reset: str


class FreebuffRawPayload(TypedDict):
    session: FreebuffSessionRaw
    usage: FreebuffUsageRaw


class FreebuffProvider(ProviderAccount):
    """Freebuff usage checker."""

    slug = "freebuff"
    name = "Freebuff"
    state_dir = "freebuff_usage"

    def __init__(self) -> None:
        super().__init__()
        self.cred_file = resolve_path(settings.paths.freebuff_credentials)

    def provider_name(self) -> str:
        return "Freebuff"

    def get_credentials(self) -> FreebuffCredentials:
        data = cast(FreebuffCredentialFile, json.loads(self.cred_file.read_text()))
        profile = data["default"]
        if "tokenStore" in profile:
            assert profile["tokenStore"] == "keychain"
            # Bun initializes its native Secret Service connection at startup.
            configure_session_bus()
            token = subprocess.run(
                ["bun", str(Path(__file__).with_name("freebuff_token.js")), str(self.cred_file)],
                stdout=subprocess.PIPE, text=True, check=True, timeout=10,
            ).stdout
            assert token
        else:
            token = profile["authToken"]
        return FreebuffCredentials(
            id=profile["id"], name=profile["name"], email=profile["email"],
            fingerprintId=profile["fingerprintId"], fingerprintHash=profile["fingerprintHash"],
            authToken=token,
        )

    def fetch_raw(self) -> FreebuffRawPayload:
        creds = self.get_credentials()

        # 1. Fetch overall usage and credit breakdown
        usage_resp = requests.post(
            settings.freebuff.usage_url,
            headers={
                "Authorization": f"Bearer {creds['authToken']}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={"fingerprintId": creds["fingerprintId"]},
            timeout=30,
        )
        usage_resp.raise_for_status()

        # 2. Fetch session and rate limit details
        session_resp = requests.get(
            settings.freebuff.api_url,
            headers={
                "Authorization": f"Bearer {creds['authToken']}",
                "Accept": "application/json",
            },
            timeout=30,
        )
        session_resp.raise_for_status()

        return cast(
            FreebuffRawPayload,
            {
                "usage": usage_resp.json(),
                "session": session_resp.json(),
            },
        )

    def to_rows(self, raw: FreebuffRawPayload) -> list[UsageRow]:
        rows: list[UsageRow] = []
        session = raw["session"]
        status = session.get("status", "none")

        # 1. Hourly Session Lease Limit
        if status == "active":
            remaining = session.get("remainingMs")
            remaining_val = remaining if remaining is not None else 3600000
            # Active session lease is 1 hour (3,600,000 ms)
            pct_used = 100 - round((remaining_val / 3600000) * 100)
            expires_at = _parse_dt(session.get("expiresAt"))
            rows.append(
                UsageRow(
                    identifier="Freebuff (Session Lease)",
                    pct_used=pct_used,
                    reset_at=expires_at,
                )
            )
        else:
            # Idle/no active session: 0% usage, 100% available
            rows.append(
                UsageRow(
                    identifier="Freebuff (Session Lease)",
                    pct_used=0,
                    reset_at=None,
                )
            )

        # 2. Daily Session Quota Limit (Limit is 5 sessions)
        if status == "active":
            rate_limit = session.get("rateLimit")
            if rate_limit:
                recent_count = rate_limit.get("recentCount", 0)
                limit = rate_limit.get("limit", 5)
                pct_used = round((recent_count / limit) * 100)
                reset_at = _parse_dt(rate_limit.get("resetAt"))
                rows.append(
                    UsageRow(
                        identifier="Freebuff (Daily Quota)",
                        pct_used=pct_used,
                        reset_at=reset_at,
                    )
                )
        else:
            # Default to 0% used when idle
            rows.append(
                UsageRow(
                    identifier="Freebuff (Daily Quota)",
                    pct_used=0,
                    reset_at=None,
                )
            )

        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        pass


def _parse_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
