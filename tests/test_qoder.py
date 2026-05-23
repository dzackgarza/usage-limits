"""Provider normalization test for Qoder.

Exercises the fetch_raw -> to_rows pipeline against the live Qoder OpenAPI.
Qoder reads its access token from the cockpit-tools account store
(~/.antigravity_cockpit/qoder_accounts/) and calls the credit usage API.
"""

from __future__ import annotations

from usage_limits.providers.qoder import QoderProvider


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
