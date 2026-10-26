"""Provider normalization tests for Claude.

Uses a captured real API response to exercise the
``fetch_raw`` → ``to_rows`` pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from usage_limits.providers.claude import ClaudeProvider
from usage_limits.auth.store import CredentialStore

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_claude_to_rows_with_captured_fixture() -> None:
    provider = ClaudeProvider()
    raw = json.loads((FIXTURE_DIR / "claude_response.json").read_text())
    rows = provider.to_rows(raw)

    assert len(rows) == 2

    five_hour = rows[0]
    assert five_hour.identifier == "Claude (5h)"
    assert five_hour.pct_used == 5.0
    assert five_hour.is_exhausted is False
    assert five_hour.reset_at == datetime(2026, 5, 23, 15, 0, 0, 171921, tzinfo=UTC)

    seven_day = rows[1]
    assert seven_day.identifier == "Claude (7d)"
    assert seven_day.pct_used == 98.0
    assert seven_day.is_exhausted is False
    assert seven_day.reset_at == datetime(2026, 5, 27, 5, 0, 0, 171943, tzinfo=UTC)


def test_claude_uses_its_own_oauth_credential(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path)
    store.save(
        "claude",
        "default",
        {
            "access_token": "stored-access-token",
            "refresh_token": "stored-refresh-token",
            "expires_at": "2026-11-01T00:00:00+00:00",
            "email": "default",
        },
    )
    provider = ClaudeProvider()
    provider.store = store

    assert provider.get_credentials()["access_token"] == "stored-access-token"


def test_claude_missing_credentials(tmp_path: Path) -> None:
    provider = ClaudeProvider()
    provider.store = CredentialStore(tmp_path)

    with pytest.raises(FileNotFoundError):
        provider.fetch_raw()
