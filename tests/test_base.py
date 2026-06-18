"""Tests for base provider framework models and contracts."""

from typing import Any, cast

import pytest

from usage_limits.base import ProviderAccount, UsageProvider
from usage_limits.contracts import ProviderSnapshot


def test_provider_snapshot_has_account_field() -> None:
    snap = ProviderSnapshot(provider="test", display_name="Test", status="ok")
    assert hasattr(snap, "account")
    assert snap.account is None  # default


def test_provider_account_is_subclass_of_usage_provider() -> None:
    assert issubclass(ProviderAccount, UsageProvider)


def test_provider_account_is_abstract() -> None:
    with pytest.raises(TypeError):
        cast(Any, ProviderAccount)()


class _ConcreteAccount(ProviderAccount):
    slug = "test-acct"
    name = "Test Account"
    state_dir = "test"

    def provider_name(self) -> str:
        return "Test"

    def fetch_raw(self) -> dict[str, Any]:
        return {}

    def to_rows(self, raw: dict[str, Any]) -> list[Any]:
        return []

    def should_anchor(self, rows: list[Any]) -> bool:
        return False

    def notify_always(self, rows: list[Any]) -> None:
        pass


def test_provider_account_has_account_id() -> None:
    a = _ConcreteAccount()
    assert a.account_id == "default"


def test_provider_account_accepts_custom_account_id() -> None:
    a = _ConcreteAccount(account_id="user@example.com")
    assert a.account_id == "user@example.com"
