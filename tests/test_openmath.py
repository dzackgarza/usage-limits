"""Tests for OpenMath usage limits provider."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from usage_limits.providers.openmath import OpenMathProvider, OpenMathUsageResponse

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_openmath_to_rows_with_captured_fixture() -> None:
    provider = OpenMathProvider()
    raw = json.loads((FIXTURE_DIR / "openmath_usage.json").read_text())
    rows = provider.to_rows(raw)

    assert len(rows) == 2

    five_hour = rows[0]
    assert five_hour.identifier == "OpenMath (5h)"
    assert five_hour.pct_used == 24
    assert five_hour.is_exhausted is False
    assert five_hour.reset_at == datetime(2026, 11, 3, 21, 22, 48, tzinfo=UTC)

    weekly = rows[1]
    assert weekly.identifier == "OpenMath (7d)"
    assert weekly.pct_used == 92
    assert weekly.is_exhausted is False
    assert weekly.reset_at == datetime(2026, 11, 10, 6, 22, 45, tzinfo=UTC)


def test_openmath_to_rows_exhausted_window() -> None:
    provider = OpenMathProvider()
    raw: OpenMathUsageResponse = {
        "windows": [
            {
                "limit_usd": 250.0,
                "resets_at": "2026-11-03T21:22:48Z",
                "spent_usd": 250.0,
                "window": "5h",
            }
        ]
    }
    rows = provider.to_rows(raw)
    assert len(rows) == 1
    assert rows[0].pct_used == 100
    assert rows[0].is_exhausted is True


def test_openmath_to_rows_empty_windows() -> None:
    provider = OpenMathProvider()
    raw: OpenMathUsageResponse = {"windows": []}
    rows = provider.to_rows(raw)
    assert rows == []


def test_openmath_to_rows_missing_key_raises_keyerror() -> None:
    provider = OpenMathProvider()
    raw = {
        "windows": [
            {
                "limit_usd": 250.0,
                "resets_at": "2026-11-03T21:22:48Z",
                "window": "5h",
            }
        ]
    }
    with pytest.raises(KeyError):
        provider.to_rows(cast(OpenMathUsageResponse, raw))


def test_openmath_to_rows_unknown_window_raises_keyerror() -> None:
    provider = OpenMathProvider()
    raw = {
        "windows": [
            {
                "limit_usd": 250.0,
                "spent_usd": 10.0,
                "resets_at": "2026-11-03T21:22:48Z",
                "window": "unknown_window",
            }
        ]
    }
    with pytest.raises(KeyError):
        provider.to_rows(cast(OpenMathUsageResponse, raw))


def test_openmath_missing_credentials_raises_error() -> None:
    provider = OpenMathProvider()
    env_token = os.environ.pop("OPENMATH_SESSION_TOKEN", None)
    env_token_alt = os.environ.pop("OPENMATH_TOKEN", None)
    try:
        with pytest.raises((FileNotFoundError, KeyError)):
            provider.fetch_raw()
    finally:
        if env_token is not None:
            os.environ["OPENMATH_SESSION_TOKEN"] = env_token
        if env_token_alt is not None:
            os.environ["OPENMATH_TOKEN"] = env_token_alt
