"""Tests for the Trae provider."""

from __future__ import annotations

import json
from pathlib import Path

from usage_limits.providers.trae import TraeProvider, TraeUsageResponse

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_trae_to_rows_parses_highest_tier_pack() -> None:
    """Trae should select the highest-tier non-promo pack and report basic+bonus."""
    with open(FIXTURE_DIR / "trae-usage.json") as f:
        raw: TraeUsageResponse = json.load(f)

    rows = TraeProvider().to_rows(raw)

    # Should have 2 rows: basic and bonus for Pro pack (highest tier after filtering PromoCode)
    assert len(rows) == 2

    # First row: basic quota
    assert rows[0].identifier == "Trae (Pro - basic)"
    # 120 / 200 * 100 = 60%
    assert rows[0].pct_used == 60.0
    assert rows[0].reset_at is None

    # Second row: bonus quota
    assert rows[1].identifier == "Trae (Pro - bonus)"
    # 10 / 50 * 100 = 20%
    assert rows[1].pct_used == 20.0
    assert rows[1].reset_at is None


def test_trae_filters_promocode_packs() -> None:
    """PromoCode packs (product_type=3) should be excluded from tier selection."""
    with open(FIXTURE_DIR / "trae-usage.json") as f:
        raw: TraeUsageResponse = json.load(f)

    rows = TraeProvider().to_rows(raw)

    # PromoCode pack (type 3) has 50/100 = 50%, but Pro (type 1) is higher tier
    # So rows should reflect Pro, not PromoCode
    assert all("PromoCode" not in r.identifier for r in rows)
    assert all("Pro" in r.identifier for r in rows)


def test_trae_exhausted_basic() -> None:
    """When basic usage >= limit, the row should be exhausted."""
    raw: TraeUsageResponse = {
        "code": 0,
        "user_entitlement_pack_list": [
            {
                "product_type": 0,
                "status": 1,
                "entitlement_base_info": {
                    "product_type": 0,
                    "quota": {
                        "basic_usage_limit": 50.0,
                        "bonus_usage_limit": 0.0,
                    },
                    "end_time": 1748044800,
                    "product_extra": {"subscription_extra": None},
                },
                "usage": {
                    "basic_usage_amount": 50.0,
                    "bonus_usage_amount": 0.0,
                    "is_flash_consuming": False,
                    "pay_go_amount": 0.0,
                },
                "next_billing_time": 0,
            }
        ],
    }

    rows = TraeProvider().to_rows(raw)
    assert len(rows) == 1
    assert rows[0].is_exhausted is True
