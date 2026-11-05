"""Provider normalization tests for Claude.

Uses a captured real API response to exercise the
``fetch_raw`` → ``to_rows`` pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from usage_limits.providers.claude import ClaudeProvider, ClaudeUsageResponse
from usage_limits.auth.store import CredentialStore

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_claude_to_rows_with_captured_fixture() -> None:
    provider = ClaudeProvider()
    raw = json.loads((FIXTURE_DIR / "claude_response.json").read_text())
    rows = provider.to_rows(raw)

    assert len(rows) == 3

    weekly_all = rows[0]
    assert weekly_all.identifier == "Claude (weekly)"
    assert weekly_all.pct_used == 100
    assert weekly_all.is_exhausted is True
    assert weekly_all.reset_at == datetime(2026, 11, 4, 5, 0, 0, 206173, tzinfo=UTC)

    weekly_scoped = rows[1]
    assert weekly_scoped.identifier == "Claude (Fable)"
    assert weekly_scoped.pct_used == 77
    assert weekly_scoped.is_exhausted is False
    assert weekly_scoped.reset_at == datetime(2026, 11, 4, 5, 0, 0, 206332, tzinfo=UTC)

    spend = rows[2]
    assert spend.identifier == "Claude (API Spend $250)"
    assert spend.pct_used == 100
    assert spend.is_exhausted is True
    assert spend.reset_at == datetime(2026, 11, 5, 7, 59, 0, tzinfo=UTC)


def test_claude_to_rows_empty_limits() -> None:
    """An API response with empty limits and no spend window produces no rows."""
    provider = ClaudeProvider()
    raw: ClaudeUsageResponse = {
        "limits": [],
        "iguana_necktie": None,
        "cedar_ember": None,
    }
    rows = provider.to_rows(raw)
    assert rows == []


def test_claude_saved_resets_from_grant_response() -> None:
    provider = ClaudeProvider()
    raw: ClaudeUsageResponse = {
        "limits": [],
        "iguana_necktie": None,
        "cedar_ember": {
            "eligible": True,
            "ineligible_reason": None,
            "grants": [
                {
                    "resets_left": 1,
                    "starts_at": "2026-09-22T16:00:00+00:00",
                    "ends_at": "2026-10-22T16:00:00+00:00",
                    "paused": False,
                    "usable_now": True,
                }
            ],
        },
    }

    resets = provider.saved_resets(raw, at=datetime(2026, 9, 26, tzinfo=UTC))

    assert resets.available_count == 1
    assert resets.applicable_now_count == 1
    assert resets.usage_url == "https://claude.ai/settings/usage"


def test_claude_saved_resets_no_grant() -> None:
    provider = ClaudeProvider()
    raw: ClaudeUsageResponse = {
        "limits": [],
        "iguana_necktie": None,
        "cedar_ember": {
            "eligible": False,
            "ineligible_reason": "no_grant",
            "grants": [],
        },
    }

    resets = provider.saved_resets(raw, at=datetime(2026, 11, 4, tzinfo=UTC))

    assert resets.available_count == 0
    assert resets.applicable_now_count == 0


def test_claude_live_usage_includes_reset_inventory() -> None:
    raw = ClaudeProvider().fetch_raw()

    assert raw["cedar_ember"] is not None


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
