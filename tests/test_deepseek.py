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


def test_to_rows_computes_pct_from_balance_and_max_amount(provider: DeepseekProvider) -> None:
    """With default max_amount=10.0, $8.66 balance → ((10.0 - 8.66)/10) * 100 = 13.4%."""
    raw = {
        "is_available": True,
        "balance_infos": [
            {
                "currency": "USD",
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
    assert "$10.00" in row.identifier
    assert row.pct_used == pytest.approx(13.4, abs=0.01)
    assert not row.is_exhausted


def test_to_rows_zero_balance_is_one_hundred_percent(provider: DeepseekProvider) -> None:
    """Zero balance → ((10 - 0)/10) * 100 = 100% used."""
    raw = {
        "is_available": True,
        "balance_infos": [
            {
                "currency": "USD",
                "total_balance": "0.00",
                "granted_balance": "0.00",
                "topped_up_balance": "0.00",
            }
        ],
    }
    rows = provider.to_rows(raw)
    assert len(rows) == 1
    assert rows[0].pct_used == 100.0


def test_to_rows_full_balance_is_zero_percent(provider: DeepseekProvider) -> None:
    """Full balance of $10.00 → ((10 - 10)/10) * 100 = 0% used."""
    raw = {
        "is_available": True,
        "balance_infos": [
            {
                "currency": "USD",
                "total_balance": "10.00",
                "granted_balance": "0.00",
                "topped_up_balance": "10.00",
            }
        ],
    }
    rows = provider.to_rows(raw)
    assert len(rows) == 1
    assert rows[0].pct_used == 0.0


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

