from __future__ import annotations

from datetime import UTC, datetime

from usage_limits.providers.antigravity import AntigravityAccount


def test_versioned_client_identity_returns_all_authoritative_summary_windows() -> None:
    provider = AntigravityAccount.resolve_accounts()[0]

    raw = provider.fetch_raw()
    rows = provider.to_rows(raw)
    by_id = {row.identifier: row for row in rows}

    expected_buckets = {
        f"{group['displayName']} ({bucket['window']})": bucket
        for group in raw["groups"]
        for bucket in group["buckets"]
    }
    assert set(expected_buckets) == {
        "Gemini Models (5h)",
        "Gemini Models (weekly)",
        "Claude and GPT models (5h)",
        "Claude and GPT models (weekly)",
    }
    labels = {"5h": "5h", "weekly": "Weekly"}
    for identifier, bucket in expected_buckets.items():
        group_name, window = identifier.rsplit(" (", 1)
        row = by_id[f"{group_name} ({labels[window[:-1]]})"]
        assert row.pct_used == round((1.0 - bucket["remainingFraction"]) * 100.0)
        reset_time = bucket.get("resetTime")
        expected_reset = (
            None
            if reset_time is None
            else datetime.fromisoformat(reset_time.replace("Z", "+00:00")).astimezone(
                UTC
            )
        )
        assert row.reset_at == expected_reset

    assert (
        by_id["Gemini Models (5h)"].reset_at != by_id["Gemini Models (Weekly)"].reset_at
    )
