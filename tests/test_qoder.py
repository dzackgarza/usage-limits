"""Provider normalization test for Qoder.

Exercises the fetch_raw -> to_rows pipeline against the live Qoder OpenAPI.
Qoder reads its access token from the cockpit-tools account store
(~/.antigravity_cockpit/qoder_accounts/) and calls the credit usage API.
"""

from __future__ import annotations

from typing import cast

from usage_limits.providers.qoder import QoderCredentials, QoderProvider


def test_qoder_live_api() -> None:
    """Qoder fetch_raw + to_rows against live API must produce valid rows."""
    provider = QoderProvider()
    raw = provider.fetch_raw()
    rows = provider.to_rows(raw)

    # Must have credit_usage with userQuota
    assert "userQuota" in raw["credit_usage"]

    # Must produce at least one row (user quota)
    assert len(rows) >= 1

    # Each row should have identifier, pct_used, is_exhausted
    for row in rows:
        assert row.identifier is not None
        assert row.pct_used >= 0
        assert isinstance(row.is_exhausted, bool)


def test_qoder_skips_zero_total_bucket() -> None:
    """to_rows must not fabricate a UsageRow when userQuota.total is 0.

    Reproduce: API returns total=0.0 for a Community plan, provider's else
    branch falls through to .get("percentage", 0.0) and produces a row
    claiming 0% used / not exhausted — indistinguishable from real zero usage.
    """
    raw = {
        "token": "test",
        "email": "test@example.com",
        "user_id": "test",
        "plan_type": "Test",
        "credit_usage": {
            "userQuota": {
                "total": 0.0,
                "used": 0.0,
                "percentage": 0.0,
                "remaining": 0.0,
                "unit": "credits",
            },
            "totalUsagePercentage": 0.0,
            "isQuotaExceeded": True,
        },
    }
    rows = QoderProvider().to_rows(cast(QoderCredentials, raw))

    # TotalUsagePercentage row is always honest (API-provided value)
    assert any("Total" in r.identifier for r in rows)

    # Must NOT produce a userQuota row — total=0 is unparseable, not "0% used"
    user_rows = [r for r in rows if "Total" not in r.identifier]
    assert len(user_rows) == 0, (
        f"Fabricated {len(user_rows)} row(s) from quota with total=0: "
        f"{[r.identifier for r in user_rows]}"
    )
