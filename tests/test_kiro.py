"""Provider normalization test for Kiro.

Exercises the fetch_raw -> to_rows pipeline. Kiro reads credentials from
~/.local/share/kiro-cli/data.sqlite3, refreshes the access token if needed,
and calls the AWS CodeWhisperer getUsageLimits API.
"""

from __future__ import annotations

import json
import sqlite3
from typing import cast

from usage_limits.providers.kiro import KiroProvider


def test_kiro_live_api() -> None:
    """Kiro fetch_raw + to_rows against live API must produce valid rows."""
    provider = KiroProvider()
    raw = provider.fetch_raw()
    rows = provider.to_rows(raw)

    # Must have usageBreakdownList
    assert len(raw["usageBreakdownList"]) >= 1

    # Must produce at least one row
    assert len(rows) >= 1

    # Each row should have identifier, pct_used, is_exhausted
    for row in rows:
        assert row.identifier is not None
        assert row.pct_used >= 0
        assert isinstance(row.is_exhausted, bool)


def test_kiro_refresh_persists_rotated_refresh_token(tmp_path) -> None:
    """A refresh must replace both tokens in Kiro CLI's credential record."""
    db_path = tmp_path / "data.sqlite3"
    original = {
        "access_token": "expired-access-token",
        "refresh_token": "consumed-refresh-token",
        "provider": "Google",
        "expires_at": "2026-10-26T00:00:00Z",
    }
    refreshed = {
        "accessToken": "new-access-token",
        "refreshToken": "rotated-refresh-token",
        "expiresIn": 3600,
        "profileArn": "arn:aws:codewhisperer:us-east-1:699475941385:profile/example",
    }

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE auth_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO auth_kv (key, value) VALUES (?, ?)",
            ("kirocli:social:token", json.dumps(original)),
        )

    provider = KiroProvider()
    provider.db_path = db_path
    provider._persist_refreshed_token(original, refreshed)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM auth_kv WHERE key = 'kirocli:social:token'"
        ).fetchone()
    assert row is not None
    stored = cast(dict[str, str], json.loads(row[0]))
    assert stored["access_token"] == "new-access-token"
    assert stored["refresh_token"] == "rotated-refresh-token"
    assert stored["provider"] == "Google"
