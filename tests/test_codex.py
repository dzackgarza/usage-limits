"""Tests for OpenAI Codex provider.

Proves correct parsing of WHAM usage responses and correct persistence of
rotated OAuth refresh tokens during 401 token refresh.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest
import requests
import responses

from usage_limits.auth.store import CredentialStore
from usage_limits.config import settings
from usage_limits.providers.codex import CodexProvider


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


def test_codex_default_refresh_persists_rotated_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Default account (~/.codex/auth.json) refreshes on 401 and saves rotated refresh token."""
    # Override the auth file path to a temp file
    auth_file = tmp_path / "auth.json"
    monkeypatch.setattr(settings.paths, "codex_auth", str(auth_file))

    # Initialize the auth file with stale credentials
    initial_data = {
        "tokens": {
            "access_token": "old_access",
            "refresh_token": "old_refresh",
            "id_token": "some_id",
            "account_id": "default",
        }
    }
    auth_file.write_text(json.dumps(initial_data))

    provider = CodexProvider(account_id="default")

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


def test_codex_store_refresh_persists_rotated_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
