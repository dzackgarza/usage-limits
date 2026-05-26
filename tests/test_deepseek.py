"""Tests for the DeepSeek API provider."""

from __future__ import annotations

import os

import pytest

from usage_limits.providers.deepseek import DeepseekProvider


@pytest.fixture
def provider() -> DeepseekProvider:
    return DeepseekProvider()


def test_no_api_key_returns_empty_rows(provider: DeepseekProvider) -> None:
    """When DEEPSEEK_API_KEY is unset, fetch_raw returns empty and to_rows yields []."""
    key = os.environ.pop("DEEPSEEK_API_KEY", None)
    try:
        raw = provider.fetch_raw()
        assert raw == {"is_available": False, "balance_infos": []}
        rows = provider.to_rows(raw)
        assert rows == []
    finally:
        if key is not None:
            os.environ["DEEPSEEK_API_KEY"] = key


def test_to_rows_balance_available(provider: DeepseekProvider) -> None:
    """to_rows produces a single non-exhausted row when balance is positive."""
    raw = {
        "is_available": True,
        "balance_infos": [
            {
                "currency": "CNY",
                "total_balance": "8.66",
                "granted_balance": "0.00",
                "topped_up_balance": "8.66",
            }
        ],
    }
    rows = provider.to_rows(raw)
    assert len(rows) == 1
    row = rows[0]
    assert "DeepSeek" in row.identifier
    assert row.pct_used == 0.0


def test_to_rows_balance_exhausted(provider: DeepseekProvider) -> None:
    """to_rows produces an exhausted row when balance is zero."""
    raw = {
        "is_available": True,
        "balance_infos": [
            {
                "currency": "CNY",
                "total_balance": "0.00",
                "granted_balance": "0.00",
                "topped_up_balance": "0.00",
            }
        ],
    }
    rows = provider.to_rows(raw)
    assert len(rows) == 1
    assert rows[0].is_exhausted


def test_to_rows_not_available(provider: DeepseekProvider) -> None:
    """to_rows returns [] when the API reports the account is not available."""
    raw = {"is_available": False, "balance_infos": []}
    assert provider.to_rows(raw) == []


@pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)
def test_live_api_with_real_key(provider: DeepseekProvider) -> None:
    """When DEEPSEEK_API_KEY is set, fetch_raw returns real data from the API."""
    raw = provider.fetch_raw()
    assert isinstance(raw, dict)
    assert "is_available" in raw
    assert "balance_infos" in raw
    rows = provider.to_rows(raw)
    assert isinstance(rows, list)
