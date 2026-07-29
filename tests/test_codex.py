"""Tests for OpenAI Codex provider.

Proves correct parsing of WHAM usage responses and correct persistence of
rotated OAuth refresh tokens during 401 token refresh.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import responses

from usage_limits.auth.store import CredentialStore, StoredCredential
from usage_limits.config import settings
from usage_limits.providers.codex import CodexProvider, WhamUsageResponse
from usage_limits.registry import collect_all


def test_codex_live_collection_returns_usage_rows_for_configured_accounts() -> None:
    """Live Codex accounts resolve and produce rows or honest reauth errors."""
    collection = collect_all(providers=["codex"])
    snapshots = {snapshot.account: snapshot for snapshot in collection.providers}

    assert set(snapshots) == {"dzackgarza@gmail.com", "zack@ncts.ntu.edu.tw"}
    for _account, snapshot in snapshots.items():
        if snapshot.status == "ok":
            assert snapshot.errors == []
            identifiers = {row.identifier for row in snapshot.rows}
            assert any(i in identifiers for i in ["Codex (5h)", "Codex (7d)"])
        else:
            # An invalidated refresh token must surface as an honest error,
            # not fabricated zero-usage rows.
            assert len(snapshot.errors) >= 1
            assert snapshot.errors[0].type == "oauthreauthrequirederror"


def test_codex_to_rows_parses_wham_windows() -> None:
    """to_rows produces separate rows for 5h and 7d windows with correct pct_used."""
    provider = CodexProvider(account_id="test@example.com")
    raw: WhamUsageResponse = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 15.4,
                "reset_at": 1718712345,
            },
            "secondary_window": {
                "used_percent": 65.6,
                "reset_at": 1718798765,
            },
        }
    }
    rows = provider.to_rows(raw)

    assert len(rows) == 2
    assert rows[0].identifier == "Codex (5h)"
    assert rows[0].pct_used == 15
    assert rows[0].reset_at is not None

    assert rows[1].identifier == "Codex (7d)"
    assert rows[1].pct_used == 66
    assert rows[1].reset_at is not None


def test_codex_to_rows_handles_missing_secondary_window() -> None:
    """to_rows handles cases where secondary window is missing from upstream."""
    provider = CodexProvider(account_id="test@example.com")
    raw: WhamUsageResponse = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 30.0,
                "reset_at": None,
            },
            "secondary_window": None,
        }
    }
    rows = provider.to_rows(raw)

    assert len(rows) == 1
    assert rows[0].identifier == "Codex (5h)"
    assert rows[0].pct_used == 30
    assert rows[0].reset_at is None


def test_codex_to_rows_parses_wham_windows_prolite() -> None:
    """to_rows produces a single 7d row for prolite standard model
    when secondary window is missing.
    """
    provider = CodexProvider(account_id="test@example.com")
    raw: WhamUsageResponse = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 2.0,
                "reset_at": 1784488523,
                "limit_window_seconds": 604800,
            },
            "secondary_window": None,
        }
    }
    rows = provider.to_rows(raw)

    assert len(rows) == 1
    assert rows[0].identifier == "Codex (7d)"
    assert rows[0].pct_used == 2


def test_codex_to_rows_handles_null_additional_rate_limits() -> None:
    """to_rows accepts the live WHAM shape where no extra model bucket is null."""
    provider = CodexProvider(account_id="test@example.com")
    raw: WhamUsageResponse = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 41.0,
                "reset_at": 1782715196,
                "limit_window_seconds": 18000,
                "reset_after_seconds": 15200,
            },
            "secondary_window": {
                "used_percent": 29.0,
                "reset_at": 1783295537,
                "limit_window_seconds": 604800,
                "reset_after_seconds": 595541,
            },
        },
        "additional_rate_limits": None,
    }

    rows = provider.to_rows(raw)

    assert [row.identifier for row in rows] == ["Codex (5h)", "Codex (7d)"]
    assert [row.pct_used for row in rows] == [41, 29]


def test_codex_to_rows_includes_additional_spark_bucket() -> None:
    """to_rows parses the Codex Spark additional window as its own two rows."""
    provider = CodexProvider(account_id="test@example.com")
    raw: WhamUsageResponse = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 15.4,
                "reset_at": 1718712345,
            },
            "secondary_window": {
                "used_percent": 65.6,
                "reset_at": 1718798765,
            },
        },
        "additional_rate_limits": [
            {
                "limit_name": "GPT-5.3-Codex-Spark",
                "metered_feature": "codex_bengalfox",
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 18.0,
                        "reset_at": 1718720000,
                        "limit_window_seconds": 432000,
                    },
                    "secondary_window": {
                        "used_percent": 5.0,
                        "reset_at": 1718798765,
                        "limit_window_seconds": 604800,
                    },
                },
            }
        ],
    }
    rows = provider.to_rows(raw)

    assert len(rows) == 4
    assert rows[2].identifier == "Codex Spark (5d)"
    assert rows[2].pct_used == 18
    assert rows[3].identifier == "Codex Spark (7d)"
    assert rows[3].pct_used == 5


def test_codex_should_anchor_zero_codex_5h_with_weekly_capacity() -> None:
    """Codex warmup fires only when the matching 5h bucket is empty and 7d is open."""
    provider = CodexProvider(account_id="test@example.com")
    raw: WhamUsageResponse = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 0.0,
                "reset_at": None,
            },
            "secondary_window": {
                "used_percent": 65.0,
                "reset_at": 1718798765,
            },
        }
    }
    rows = provider.to_rows(raw)

    assert provider.should_anchor(rows) is True


def test_codex_should_not_anchor_nonzero_5h_bucket() -> None:
    """Codex warmup does not fire once the 5h bucket has any visible usage."""
    provider = CodexProvider(account_id="test@example.com")
    raw: WhamUsageResponse = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 1.0,
                "reset_at": None,
            },
            "secondary_window": {
                "used_percent": 65.0,
                "reset_at": 1718798765,
            },
        }
    }
    rows = provider.to_rows(raw)

    assert provider.should_anchor(rows) is False


def test_codex_should_not_anchor_when_matching_weekly_bucket_exhausted() -> None:
    """Codex warmup does not fire when the matching 7d bucket is exhausted."""
    provider = CodexProvider(account_id="test@example.com")
    raw: WhamUsageResponse = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 0.0,
                "reset_at": None,
            },
            "secondary_window": {
                "used_percent": 100.0,
                "reset_at": 1718798765,
            },
        }
    }
    rows = provider.to_rows(raw)

    assert provider.should_anchor(rows) is False


def test_codex_should_anchor_zero_spark_5h_with_weekly_capacity() -> None:
    """Codex Spark 5h buckets use the same warmup rule as the main Codex bucket."""
    provider = CodexProvider(account_id="test@example.com")
    raw: WhamUsageResponse = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 25.0,
                "reset_at": 1718712345,
            },
            "secondary_window": {
                "used_percent": 100.0,
                "reset_at": 1718798765,
            },
        },
        "additional_rate_limits": [
            {
                "limit_name": "GPT-5.3-Codex-Spark",
                "metered_feature": "codex_bengalfox",
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 0.0,
                        "reset_at": None,
                        "limit_window_seconds": 18000,
                    },
                    "secondary_window": {
                        "used_percent": 5.0,
                        "reset_at": 1718798765,
                        "limit_window_seconds": 604800,
                    },
                },
            }
        ],
    }
    rows = provider.to_rows(raw)

    assert provider.should_anchor(rows) is True


def test_codex_should_not_anchor_zero_spark_non_5h_bucket() -> None:
    """Only 5h rows trigger warmup; other Spark windows do not."""
    provider = CodexProvider(account_id="test@example.com")
    raw: WhamUsageResponse = {
        "rate_limit": {
            "primary_window": {
                "used_percent": 25.0,
                "reset_at": 1718712345,
            },
            "secondary_window": {
                "used_percent": 65.0,
                "reset_at": 1718798765,
            },
        },
        "additional_rate_limits": [
            {
                "limit_name": "GPT-5.3-Codex-Spark",
                "metered_feature": "codex_bengalfox",
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 0.0,
                        "reset_at": None,
                        "limit_window_seconds": 432000,
                    },
                    "secondary_window": {
                        "used_percent": 5.0,
                        "reset_at": 1718798765,
                        "limit_window_seconds": 604800,
                    },
                },
            }
        ],
    }
    rows = provider.to_rows(raw)

    assert provider.should_anchor(rows) is False


def test_codex_store_refresh_persists_rotated_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """CredentialStore account refreshes on 401 and saves rotated refresh token."""
    # Direct CredentialStore to a temp directory
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )

    store = CredentialStore()
    initial_cred: StoredCredential = {
        "access_token": "old_access",
        "refresh_token": "old_refresh",
        "expires_at": None,
        "email": "test@example.com",
    }
    store.save("codex", "test@example.com", initial_cred)

    provider = CodexProvider(account_id="test@example.com")

    with responses.RequestsMock() as rsps:
        # First request fails with 401
        rsps.add(
            responses.GET,
            settings.codex.api_url,
            status=401,
        )
        # OAuth refresh returns rotated tokens
        rsps.add(
            responses.POST,
            "https://auth.openai.com/oauth/token",
            json={
                "access_token": "new_access",
                "refresh_token": "new_refresh",
                "expires_in": 3600,
            },
            status=200,
        )
        # Second request succeeds
        rsps.add(
            responses.GET,
            settings.codex.api_url,
            json={
                "rate_limit": {
                    "primary_window": {"used_percent": 20.0, "reset_at": None},
                    "secondary_window": None,
                }
            },
            status=200,
        )

        raw = provider.fetch_raw()
        assert raw["rate_limit"]["primary_window"]["used_percent"] == 20.0

        # Assert rotated refresh token is saved to the store
        saved = store.get("codex", "test@example.com")
        assert saved["access_token"] == "new_access"
        assert saved["refresh_token"] == "new_refresh"


def test_codex_store_refresh_marks_invalidated_token_reauth_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Invalidated refresh tokens become owned reauth-required credential state."""
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )

    store = CredentialStore()
    store.save(
        "codex",
        "test@example.com",
        {
            "access_token": "old_access",
            "refresh_token": "old_refresh",
            "expires_at": None,
            "email": "test@example.com",
        },
    )

    provider = CodexProvider(account_id="test@example.com")

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            settings.codex.api_url,
            status=401,
        )
        rsps.add(
            responses.POST,
            "https://auth.openai.com/oauth/token",
            json={
                "error": {
                    "message": "Your session has ended. Please log in again.",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "refresh_token_invalidated",
                }
            },
            status=401,
        )

        with pytest.raises(RuntimeError):
            provider.fetch_raw()

    saved = store.get("codex", "test@example.com")
    assert saved["access_token"] == "old_access"
    assert saved["refresh_token"] == "old_refresh"
    assert saved["requires_reauth"] is True
    assert saved["reauth_error_code"] == "refresh_token_invalidated"
    assert saved["reauth_status_code"] == 401


def test_codex_reauth_required_store_account_fails_before_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A known reauth-required account must not keep probing Codex with stale tokens."""
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )

    store = CredentialStore()
    store.save(
        "codex",
        "test@example.com",
        {
            "access_token": "old_access",
            "refresh_token": "old_refresh",
            "expires_at": None,
            "email": "test@example.com",
            "requires_reauth": True,
            "reauth_error_code": "refresh_token_invalidated",
            "reauth_status_code": 401,
            "reauth_at": "2026-06-29T06:00:00+00:00",
        },
    )

    provider = CodexProvider(account_id="test@example.com")

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        with pytest.raises(RuntimeError):
            provider.fetch_raw()

        assert len(rsps.calls) == 0


def test_codex_resolve_accounts_prefers_recent_login(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Recent store credentials are selected before older store entries."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )

    store = CredentialStore()
    now = time.time()

    old_cred: StoredCredential = {
        "access_token": "old_access",
        "refresh_token": "old_refresh",
        "expires_at": "2026-06-18T12:00:00Z",
        "email": "alpha@example.com",
        "extra": {},
    }
    new_cred: StoredCredential = {
        "access_token": "new_access",
        "refresh_token": "new_refresh",
        "expires_at": "2026-06-18T12:00:00Z",
        "email": "zeta@example.com",
        "extra": {},
    }

    store.save("codex", "alpha@example.com", old_cred)
    store.save("codex", "zeta@example.com", new_cred)

    os.utime(
        store._credential_path("codex", "alpha@example.com"),
        (now - 7200, now - 7200),
    )
    os.utime(
        store._credential_path("codex", "zeta@example.com"),
        (now - 3600, now - 3600),
    )

    accounts = CodexProvider.resolve_accounts()
    assert [acct.account_id for acct in accounts] == [
        "zeta@example.com",
        "alpha@example.com",
    ]


def test_codex_resolve_accounts_keeps_reauth_required_accounts_after_usable_accounts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reauth markers remain visible without becoming the default account."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )

    store = CredentialStore()
    now = time.time()
    usable_cred: StoredCredential = {
        "access_token": "usable_access",
        "refresh_token": "usable_refresh",
        "expires_at": "2026-06-18T12:00:00Z",
        "email": "usable@example.com",
        "extra": {},
    }
    reauth_cred: StoredCredential = {
        "access_token": "reauth_access",
        "refresh_token": "reauth_refresh",
        "expires_at": "2026-06-18T12:00:00Z",
        "email": "reauth@example.com",
        "requires_reauth": True,
        "reauth_error_code": "refresh_token_invalidated",
        "reauth_status_code": 401,
        "reauth_at": "2026-06-29T06:00:00+00:00",
        "extra": {},
    }

    store.save("codex", "usable@example.com", usable_cred)
    store.save("codex", "reauth@example.com", reauth_cred)

    os.utime(
        store._credential_path("codex", "usable@example.com"),
        (now - 7200, now - 7200),
    )
    os.utime(
        store._credential_path("codex", "reauth@example.com"),
        (now, now),
    )

    accounts = CodexProvider.resolve_accounts()
    assert [acct.account_id for acct in accounts] == [
        "usable@example.com",
        "reauth@example.com",
    ]


def test_codex_resolve_accounts_returns_empty_without_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """With no stored credentials, usage-limits resolves no accounts."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )
    _ = CredentialStore()

    accounts = CodexProvider.resolve_accounts()
    assert [acct.account_id for acct in accounts] == []
