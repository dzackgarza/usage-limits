"""Provider normalization tests for Antigravity."""

from __future__ import annotations

from datetime import UTC, datetime

from usage_limits.providers.antigravity import AntigravityProvider


def test_antigravity_to_rows_normalizes_model_usage() -> None:
    provider = AntigravityProvider()
    raw = {
        "models": [
            {
                "label": "Gemini 2.5 Flash",
                "remainingPercentage": 0.75,
                "isExhausted": False,
                "resetTime": "2026-03-10T15:00:00Z",
            },
            {
                "label": "Claude Sonnet 4.6",
                "remainingPercentage": None,
                "isExhausted": False,
                "resetTime": "2026-03-11T02:30:00Z",
            },
        ]
    }

    rows = provider.to_rows(raw)

    assert rows[0].identifier == "Antigravity: Gemini 2.5 Flash"
    assert rows[0].pct_used == 25.0
    assert rows[0].reset_at == datetime(2026, 3, 10, 15, 0, tzinfo=UTC)
    assert rows[1].identifier == "Antigravity: Claude Sonnet 4.6"
    assert rows[1].pct_used == 100.0
    assert rows[1].is_exhausted is True


def test_antigravity_availability_groups_bucket_status() -> None:
    provider = AntigravityProvider()
    rows = provider.to_rows(
        {
            "models": [
                {
                    "label": "Gemini 2.5 Flash",
                    "remainingPercentage": 0.50,
                    "isExhausted": False,
                    "resetTime": "2026-03-10T15:00:00Z",
                },
                {
                    "label": "Gemini 2.5 Pro",
                    "remainingPercentage": 0.10,
                    "isExhausted": False,
                    "resetTime": "2026-03-10T17:00:00Z",
                },
                {
                    "label": "Claude Sonnet 4.6",
                    "remainingPercentage": None,
                    "isExhausted": True,
                    "resetTime": "2026-03-11T02:30:00Z",
                },
            ]
        }
    )

    availability = {entry.name: entry for entry in provider.availability(rows)}

    assert availability["Antigravity: Flash (All)"].available_now is True
    assert availability["Antigravity: Pro (2.5)"].available_now is True
    assert availability["Antigravity: Claude (All)"].available_now is False
    assert availability["Antigravity: Claude (All)"].available_when == datetime(
        2026, 3, 11, 2, 30, tzinfo=UTC
    )
