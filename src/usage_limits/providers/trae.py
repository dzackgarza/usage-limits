"""Trae usage limits provider."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TypedDict, cast

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class TraeQuota(TypedDict):
    basic_usage_limit: float
    bonus_usage_limit: float


class TraeProductExtra(TypedDict):
    subscription_extra: dict[str, object] | None


class TraeEntitlementBaseInfo(TypedDict):
    product_type: int
    quota: TraeQuota
    end_time: int
    product_extra: TraeProductExtra


class TraeUsage(TypedDict):
    basic_usage_amount: float
    bonus_usage_amount: float
    is_flash_consuming: bool
    pay_go_amount: float


class TraeEntitlementPack(TypedDict):
    product_type: int
    status: int
    entitlement_base_info: TraeEntitlementBaseInfo
    usage: TraeUsage
    next_billing_time: int


class TraeUsageResponse(TypedDict):
    code: int
    user_entitlement_pack_list: list[TraeEntitlementPack]


# Product type priorities (higher index = higher tier)
PRODUCT_TIER_ORDER = [0, 8, 9, 1, 4, 6]  # Free, Lite, Trial, Pro, Pro+, Ultra
PRODUCT_NAMES = {
    0: "Free",
    1: "Pro",
    2: "Package",
    3: "PromoCode",
    4: "Pro+",
    6: "Ultra",
    7: "PayGo",
    8: "Lite",
    9: "Trial",
}

# Region origins
REGION_ORIGINS = {
    "CN": "https://grow-normal.trae.ai",
    "SG": "https://growsg-normal.trae.ai",
    "US": "https://growva-normal.trae.ai",
    "USTTP": "https://grow-normal.traeapi.us",
}


class TraeProvider(UsageProvider):
    """Trae usage checker (per-plan quota tracking)."""

    slug = "trae"
    name = "Trae"
    state_dir = "trae_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self) -> None:
        super().__init__()
        self.state_db = (
            Path.home()
            / ".config"
            / "Trae"
            / "User"
            / "globalStorage"
            / "storage.json"
        )

    def provider_name(self) -> str:
        return "Trae"

    def get_access_token(self) -> str:
        with open(self.state_db) as f:
            storage = json.load(f)
        auth_info = storage["iCubeAuthInfo://icube.cloudide"]
        auth_data = json.loads(auth_info)
        return auth_data["access_token"]

    def get_api_origin(self) -> str:
        """Determine API origin from stored auth or default to CN."""
        try:
            with open(self.state_db) as f:
                storage = json.load(f)
            auth_info = storage["iCubeAuthInfo://icube.cloudide"]
            auth_data = json.loads(auth_info)
            login_host = auth_data.get("loginHost", "")
            if "traeapi.us" in login_host:
                return REGION_ORIGINS["USTTP"]
            if "growsg" in login_host:
                return REGION_ORIGINS["SG"]
            if "growva" in login_host:
                return REGION_ORIGINS["US"]
        except (KeyError, json.JSONDecodeError):
            pass
        return REGION_ORIGINS["CN"]

    def fetch_raw(self) -> TraeUsageResponse:
        access_token = self.get_access_token()
        origin = self.get_api_origin()
        usage_url = f"{origin}/trae/api/v1/pay/ide_user_ent_usage"

        resp = requests.post(
            usage_url,
            headers={
                "Authorization": f"Cloud-IDE-JWT {access_token}",
                "Content-Type": "application/json",
            },
            json={"require_usage": True},
            timeout=30,
        )
        resp.raise_for_status()
        return cast(TraeUsageResponse, resp.json())

    def to_rows(self, raw: TraeUsageResponse) -> list[UsageRow]:
        rows: list[UsageRow] = []

        packs = raw["user_entitlement_pack_list"]

        # Filter out PromoCode packs
        active_packs = [p for p in packs if p["product_type"] != 3]

        if not active_packs:
            return rows

        # Find highest-tier pack
        def tier_priority(pack: TraeEntitlementPack) -> int:
            pt = pack["product_type"]
            if pt in PRODUCT_TIER_ORDER:
                return PRODUCT_TIER_ORDER.index(pt)
            return -1

        best_pack = max(active_packs, key=tier_priority)

        product_type = best_pack["product_type"]
        identity = PRODUCT_NAMES.get(product_type, f"Unknown({product_type})")

        base_info = best_pack["entitlement_base_info"]
        usage = best_pack["usage"]

        basic_limit = base_info["quota"]["basic_usage_limit"]
        basic_used = usage["basic_usage_amount"]

        if basic_limit > 0:
            pct_used = (basic_used / basic_limit) * 100
            rows.append(
                UsageRow(
                    identifier=f"Trae ({identity} - basic)",
                    pct_used=pct_used,
                    reset_at=None,
                )
            )

        # Also report bonus quota if present
        bonus_limit = base_info["quota"]["bonus_usage_limit"]
        bonus_used = usage["bonus_usage_amount"]

        if bonus_limit > 0:
            pct_used = (bonus_used / bonus_limit) * 100
            rows.append(
                UsageRow(
                    identifier=f"Trae ({identity} - bonus)",
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
                "Trae Window Open",
                "Trae credits available!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str] | None:
        return None
