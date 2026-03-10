"""Contract tests for normalized usage_limits payloads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from usage_limits.contracts import AvailabilityCollection, ProviderSnapshot, UsageCollection
from usage_limits.table import ModelAvailability, UsageRow


def test_usage_collection_serializes_rows_and_availability() -> None:
    reset_at = datetime.now(UTC) + timedelta(days=2, hours=4)
    snapshot = ProviderSnapshot(
        provider="claude",
        display_name="Claude Code",
        status="ok",
        rows=[UsageRow(identifier="Claude (5h)", pct_used=100.0, reset_at=reset_at)],
        availability=[
            ModelAvailability(
                name="Claude",
                available_now=False,
                available_when=reset_at,
            )
        ],
    )

    payload = UsageCollection(providers=[snapshot]).model_dump(mode="json")
    provider = payload["providers"][0]
    row = provider["rows"][0]

    assert provider["provider"] == "claude"
    assert provider["display_name"] == "Claude Code"
    assert provider["availability"][0]["available_now"] is False
    assert row["identifier"] == "Claude (5h)"
    assert row["pct_used"] == 100.0
    assert row["is_exhausted"] is True
    assert row["time_until_reset"].startswith("in 2d")


def test_availability_collection_projects_usage_contract() -> None:
    reset_at = datetime.now(UTC) + timedelta(hours=5)
    usage_collection = UsageCollection(
        providers=[
            ProviderSnapshot(
                provider="codex",
                display_name="Codex",
                status="ok",
                rows=[UsageRow(identifier="Codex (5h)", pct_used=87.0, reset_at=reset_at)],
                availability=[
                    ModelAvailability(
                        name="Codex",
                        available_now=True,
                        available_when=None,
                    )
                ],
            )
        ]
    )

    payload = AvailabilityCollection.from_usage_collection(usage_collection).model_dump(mode="json")
    provider = payload["providers"][0]

    assert provider["provider"] == "codex"
    assert provider["display_name"] == "Codex"
    assert provider["availability"] == [
        {
            "name": "Codex",
            "available_now": True,
            "available_when": None,
        }
    ]
