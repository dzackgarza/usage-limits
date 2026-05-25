"""Tests for base provider framework models and contracts."""

from usage_limits.contracts import ProviderSnapshot


def test_provider_snapshot_has_account_field() -> None:
    snap = ProviderSnapshot(provider="test", display_name="Test", status="ok")
    assert hasattr(snap, "account")
    assert snap.account is None  # default
