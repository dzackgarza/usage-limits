"""DeepSeek API usage limits provider.

Queries the ``/user/balance`` endpoint to check prepaid account balance.
Requires ``DEEPSEEK_API_KEY`` env var; quietly returns no rows when unset.

A configured ``max_amount`` (default $10 USD) is used to compute the
``pct_used`` from the ``total_balance`` returned by the API.
"""

from __future__ import annotations

import os
from typing import Any, TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.table import UsageRow


class BalanceInfo(TypedDict):
    currency: str
    total_balance: str
    granted_balance: str
    topped_up_balance: str


class DeepseekBalance(TypedDict):
    is_available: bool
    balance_infos: list[BalanceInfo]


_EMPTY: DeepseekBalance = {"is_available": False, "balance_infos": []}


class DeepseekProvider(ProviderAccount):
    """DeepSeek API usage checker (prepaid balance via /user/balance)."""

    slug = "deepseek"
    name = "DeepSeek"
    state_dir = "deepseek_usage"

    def provider_name(self) -> str:
        return "DeepSeek"

    def fetch_raw(self) -> DeepseekBalance:
        api_key = os.environ["DEEPSEEK_API_KEY"]

        from usage_limits.config import settings as _cfg

        url = _cfg.deepseek.api_base.rstrip("/") + _cfg.deepseek.balance_endpoint
        resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        resp.raise_for_status()
        return cast(DeepseekBalance, resp.json())

    def to_rows(self, raw: DeepseekBalance) -> list[UsageRow]:
        if not raw["balance_infos"]:
            return []

        from usage_limits.config import settings as _cfg

        info = raw["balance_infos"][0]
        total = float(info["total_balance"])
        max_amt = _cfg.deepseek.max_amount

        pct_used = ((max_amt - total) / max_amt) * 100.0
        return [
            UsageRow(
                identifier=f"DeepSeek (${max_amt:.2f})",
                pct_used=round(pct_used),
                reset_at=None,
            )
        ]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        pass

    def metadata(self, raw: Any, rows: list[UsageRow]) -> dict[str, Any]:
        if not raw["balance_infos"]:
            return {"available": False}
        info = raw["balance_infos"][0]
        return {
            "available": raw["is_available"],
            "currency": info["currency"],
            "total_balance": info["total_balance"],
            "granted_balance": info["granted_balance"],
            "topped_up_balance": info["topped_up_balance"],
        }
