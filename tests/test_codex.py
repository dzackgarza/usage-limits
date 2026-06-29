"""Tests for OpenAI Codex provider.

Proves correct parsing of WHAM usage responses and correct persistence of
rotated OAuth refresh tokens during 401 token refresh.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import pytest
import responses

from usage_limits.auth.store import CredentialStore
from usage_limits.config import settings
from usage_limits.providers.codex import CodexProvider


def _id_token_for_email(email: str) -> str:
    def encode_json(payload: object) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return ".".join(
        [
            encode_json({"alg": "none"}),
            encode_json({"email": email}),
            "signature",
        ]
    )


def test_codex_to_rows_parses_wham_windows() -> None:
    """to_rows produces separate rows for 5h and 7d windows with correct pct_used."""
    provider = CodexProvider(account_id="test@example.com")
    raw = {
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
    raw = {
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


def test_codex_to_rows_includes_additional_spark_bucket() -> None:
    """to_rows parses the Codex Spark additional window as its own two rows."""
    provider = CodexProvider(account_id="test@example.com")
    raw = {
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


def test_codex_cli_auth_refresh_persists_rotated_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CLI auth refreshes on 401 and saves the rotated refresh token."""
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )

    # Override the auth file path to a temp file
    auth_file = tmp_path / "auth.json"
    monkeypatch.setattr(settings.paths, "codex_auth", str(auth_file))

    # Initialize the auth file with stale credentials
    initial_data = {
        "tokens": {
            "access_token": "old_access",
            "refresh_token": "old_refresh",
            "id_token": _id_token_for_email("cli@example.com"),
            "account_id": "3b84abab-e9c2-46f7-a810-88a418eaafce",
        }
    }
    auth_file.write_text(json.dumps(initial_data))

    provider = CodexProvider(account_id="cli@example.com")

    with responses.RequestsMock() as rsps:
        # First request to Codex API fails with 401
        rsps.add(
            responses.GET,
            settings.codex.api_url,
            status=401,
        )
        # OAuth token endpoint returns rotated tokens
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
        # Second request to Codex API succeeds
        rsps.add(
            responses.GET,
            settings.codex.api_url,
            json={
                "rate_limit": {
                    "primary_window": {"used_percent": 10.0, "reset_at": None},
                    "secondary_window": None,
                }
            },
            status=200,
        )

        raw = provider.fetch_raw()
        assert raw["rate_limit"]["primary_window"]["used_percent"] == 10.0

        # Assert that the auth file was updated with the rotated refresh token
        saved = json.loads(auth_file.read_text())
        assert saved["tokens"]["access_token"] == "new_access"
        assert saved["tokens"]["refresh_token"] == "new_refresh"

        saved_store = CredentialStore().get("codex", "cli@example.com")
        assert saved_store["access_token"] == "new_access"
        assert saved_store["refresh_token"] == "new_refresh"


def test_codex_store_refresh_persists_rotated_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CredentialStore account refreshes on 401 and saves rotated refresh token."""
    # Direct CredentialStore to a temp directory
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )

    store = CredentialStore()
    initial_cred = {
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


def test_codex_matching_cli_auth_supersedes_stale_store_account(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The Codex CLI auth file is a credential source for its email, not a default account."""
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )

    store = CredentialStore()
    store.save(
        "codex",
        "dzackgarza@gmail.com",
        {
            "access_token": "stale_store_access",
            "refresh_token": "stale_store_refresh",
            "expires_at": "2026-06-18T12:00:00Z",
            "email": "dzackgarza@gmail.com",
            "extra": {},
        },
    )

    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "cli_access",
                    "refresh_token": "cli_refresh",
                    "id_token": _id_token_for_email("dzackgarza@gmail.com"),
                    "account_id": "3b84abab-e9c2-46f7-a810-88a418eaafce",
                }
            }
        )
    )
    monkeypatch.setattr(settings.paths, "codex_auth", str(auth_file))

    credentials = CodexProvider(account_id="dzackgarza@gmail.com").get_credentials()

    assert credentials["access_token"] == "cli_access"
    assert credentials["refresh_token"] == "cli_refresh"


def test_codex_ignores_cockpit_accounts_and_revalidates_owned_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Codex revalidation uses usage-limits-owned storage, not cockpit runtime files."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )

    store = CredentialStore()
    store.save(
        "codex",
        "zack@ncts.ntu.edu.tw",
        {
            "access_token": "stale_store_access",
            "refresh_token": "stale_store_refresh",
            "expires_at": "2026-06-18T12:00:00Z",
            "email": "zack@ncts.ntu.edu.tw",
            "extra": {},
        },
    )

    cockpit_dir = tmp_path / ".antigravity_cockpit" / "codex_accounts"
    cockpit_dir.mkdir(parents=True)
    (cockpit_dir / "codex_account.json").write_text(
        json.dumps(
            {
                "email": "zack@ncts.ntu.edu.tw",
                "account_id": "fcff327a-1ab3-426f-b024-bf7fd73bf03d",
                "auth_mode": "oauth",
                "token_source_mode": "managed",
                "tokens": {
                    "access_token": "cockpit_access",
                    "refresh_token": "cockpit_refresh",
                    "id_token": _id_token_for_email("zack@ncts.ntu.edu.tw"),
                },
            }
        )
    )

    auth_file = tmp_path / ".codex" / "auth.json"
    monkeypatch.setattr(settings.paths, "codex_auth", str(auth_file))

    provider = CodexProvider(account_id="zack@ncts.ntu.edu.tw")

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            settings.codex.api_url,
            status=401,
            match=[
                responses.matchers.header_matcher(
                    {"Authorization": "Bearer stale_store_access"}
                )
            ],
        )
        rsps.add(
            responses.POST,
            "https://auth.openai.com/oauth/token",
            json={
                "access_token": "owned_new_access",
                "refresh_token": "owned_new_refresh",
                "expires_in": 3600,
            },
            status=200,
            match=[
                responses.matchers.urlencoded_params_matcher(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": "stale_store_refresh",
                        "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
                    }
                )
            ],
        )
        rsps.add(
            responses.GET,
            settings.codex.api_url,
            json={
                "rate_limit": {
                    "primary_window": {"used_percent": 25.0, "reset_at": None},
                    "secondary_window": None,
                }
            },
            status=200,
            match=[
                responses.matchers.header_matcher(
                    {"Authorization": "Bearer owned_new_access"}
                )
            ],
        )

        raw = provider.fetch_raw()

    assert raw["rate_limit"]["primary_window"]["used_percent"] == 25.0

    saved_store = store.get("codex", "zack@ncts.ntu.edu.tw")
    assert saved_store["access_token"] == "owned_new_access"
    assert saved_store["refresh_token"] == "owned_new_refresh"


def test_codex_resolve_accounts_prefers_recent_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Recent auth context should be selected before older store entries."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )

    store = CredentialStore()
    now = time.time()

    old_cred = {
        "access_token": "old_access",
        "refresh_token": "old_refresh",
        "expires_at": "2026-06-18T12:00:00Z",
        "email": "alpha@example.com",
        "extra": {},
    }
    new_cred = {
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

    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "cli_access",
                    "refresh_token": "cli_refresh",
                    "id_token": _id_token_for_email("zeta@example.com"),
                    "account_id": "3b84abab-e9c2-46f7-a810-88a418eaafce",
                }
            }
        )
    )
    os.utime(auth_file, (now, now))
    monkeypatch.setattr(settings.paths, "codex_auth", str(auth_file))

    accounts = CodexProvider.resolve_accounts()
    assert [acct.account_id for acct in accounts] == [
        "zeta@example.com",
        "alpha@example.com",
    ]


def test_codex_resolve_accounts_uses_cli_auth_email_without_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With only Codex CLI auth on disk, usage-limits resolves the token email."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )
    _ = CredentialStore()

    auth_file = tmp_path / "auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "tokens": {
                    "access_token": "cli_access",
                    "refresh_token": "cli_refresh",
                    "id_token": _id_token_for_email("alpha@example.com"),
                    "account_id": "3b84abab-e9c2-46f7-a810-88a418eaafce",
                }
            }
        )
    )
    monkeypatch.setattr(settings.paths, "codex_auth", str(auth_file))

    accounts = CodexProvider.resolve_accounts()
    assert [acct.account_id for acct in accounts] == ["alpha@example.com"]


def test_codex_resolve_accounts_ignores_cockpit_accounts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cockpit account files are migration/reference input, not runtime accounts."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        CredentialStore,
        "__init__",
        lambda self, root_dir=None: setattr(self, "root_dir", tmp_path / "credentials"),
    )
    _ = CredentialStore()

    auth_file = tmp_path / ".codex" / "auth.json"
    monkeypatch.setattr(settings.paths, "codex_auth", str(auth_file))

    cockpit_dir = tmp_path / ".antigravity_cockpit" / "codex_accounts"
    cockpit_dir.mkdir(parents=True)
    cockpit_file = cockpit_dir / "codex_account.json"
    cockpit_file.write_text(
        json.dumps(
            {
                "email": "cockpit@example.com",
                "account_id": "fcff327a-1ab3-426f-b024-bf7fd73bf03d",
                "auth_mode": "oauth",
                "token_source_mode": "managed",
                "tokens": {
                    "access_token": "cockpit_access",
                    "refresh_token": "cockpit_refresh",
                    "id_token": _id_token_for_email("cockpit@example.com"),
                },
            }
        )
    )

    accounts = CodexProvider.resolve_accounts()
    assert [acct.account_id for acct in accounts] == []
