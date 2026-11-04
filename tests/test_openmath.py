"""OpenMath provider tests against captured and live API responses."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from usage_limits.providers.openmath import OpenMathProvider, OpenMathUsageResponse

FIXTURE = Path(__file__).parent / "fixtures" / "openmath_usage.json"


def test_openmath_captured_response_normalizes_usage() -> None:
    raw = cast(OpenMathUsageResponse, json.loads(FIXTURE.read_text()))
    rows = OpenMathProvider().to_rows(raw)

    assert [(row.identifier, row.pct_used, row.reset_at) for row in rows] == [
        ("OpenMath (5h)", 24, datetime(2026, 11, 3, 21, 22, 48, tzinfo=UTC)),
        ("OpenMath (7d)", 92, datetime(2026, 11, 10, 6, 22, 45, tzinfo=UTC)),
    ]


def test_openmath_live_fetch_normalizes_usage() -> None:
    provider = OpenMathProvider()
    raw = provider.fetch_raw()
    rows = provider.to_rows(raw)

    assert {row.identifier for row in rows} == {"OpenMath (5h)", "OpenMath (7d)"}
    for window, row in zip(raw["windows"], rows, strict=True):
        assert row.pct_used == round(100 * window["spent_usd"] / window["limit_usd"])
        if window["resets_at"] is None:
            assert row.reset_at is None
        else:
            assert row.reset_at == datetime.fromisoformat(
                window["resets_at"].replace("Z", "+00:00")
            )


def test_openmath_missing_spend_fails_instead_of_reporting_zero() -> None:
    raw = json.loads(FIXTURE.read_text())
    del raw["windows"][0]["spent_usd"]

    with pytest.raises(KeyError):
        OpenMathProvider().to_rows(cast(OpenMathUsageResponse, raw))


def test_openmath_inactive_windows_have_no_reset_time() -> None:
    raw = cast(
        OpenMathUsageResponse,
        {
            "windows": [
                {
                    "window": "5h",
                    "limit_usd": 250.0,
                    "spent_usd": 0.0,
                    "resets_at": None,
                },
                {
                    "window": "week",
                    "limit_usd": 250.0,
                    "spent_usd": 0.0,
                    "resets_at": None,
                },
            ]
        },
    )

    rows = OpenMathProvider().to_rows(raw)

    assert [(row.identifier, row.pct_used, row.reset_at) for row in rows] == [
        ("OpenMath (5h)", 0, None),
        ("OpenMath (7d)", 0, None),
    ]
