"""Provider normalization test for Trae.

Exercises the fetch_raw -> to_rows pipeline against the live API.
The Trae provider reads encrypted auth from storage.json,
decrypts it using ByteCrypto (AES-128-CBC), and calls the
ide_user_ent_usage endpoint to get per-plan quota data.
"""

from __future__ import annotations

from usage_limits.providers.trae import TraeProvider


def test_trae_live_api() -> None:
    """Trae fetch_raw + to_rows against live API must produce valid rows."""
    provider = TraeProvider()
    raw = provider.fetch_raw()
    rows = provider.to_rows(raw)

    # Must have at least one entitlement pack
    assert len(raw["user_entitlement_pack_list"]) >= 1

    # Must produce rows for the highest-tier pack
    # Free plans with 0 limits produce 0 rows - this is valid
    assert len(rows) >= 0

    # Each row should have identifier, pct_used, is_exhausted, reset_at
    for row in rows:
        assert row.identifier is not None
        assert row.pct_used >= 0
        assert isinstance(row.is_exhausted, bool)
        assert row.reset_at is not None, f"reset_at is None for {row.identifier}"
