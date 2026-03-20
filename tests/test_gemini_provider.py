"""Tests for GeminiProvider.fetch_raw correctness against real SQLite data.

These tests verify the provider correctly queries the otlp-collector database
to count Gemini CLI API requests.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from usage_limits.providers.gemini import GeminiProvider


def _make_db(path: Path) -> None:
    """Create the minimal logs table expected by fetch_raw."""
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                trace_id TEXT,
                span_id TEXT,
                time_unix_nano INTEGER,
                observed_time_unix_nano INTEGER,
                severity_text TEXT,
                severity_number INTEGER,
                body TEXT,
                attributes TEXT,
                resource_attributes TEXT
            )
        """)


def _insert_log(
    conn: sqlite3.Connection,
    *,
    time_unix_nano: int,
    service_name: str = "gemini-cli",
    event_name: str = "gemini_cli.api_request",
) -> None:
    conn.execute(
        """
        INSERT INTO logs (trace_id, span_id, time_unix_nano, attributes, resource_attributes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "trace-1",
            f"span-{time_unix_nano}",
            time_unix_nano,
            json.dumps({"event.name": event_name}),
            json.dumps({"service.name": service_name}),
        ),
    )


def _today_nano() -> int:
    """Return a unix timestamp in nanoseconds for right now (today)."""
    return int(datetime.now(UTC).timestamp() * 1_000_000_000)


def _yesterday_nano() -> int:
    yesterday = datetime.now(UTC) - timedelta(days=1)
    return int(yesterday.timestamp() * 1_000_000_000)


# ---------------------------------------------------------------------------
# Database Query Tests - Real SQLite with Test Fixtures
# ---------------------------------------------------------------------------


def test_fetch_raw_fallback_to_local_db_when_oauth_missing(tmp_path: Path) -> None:
    """fetch_raw falls back to local DB counting when OAuth is not configured.

    Uses a temporary test database to verify the fallback mechanism.
    """
    # Create empty test database
    db_path = tmp_path / "telemetry.db"
    _make_db(db_path)

    # Provider with no OAuth credentials will use local DB
    provider = GeminiProvider()
    # Point to test database by setting instance attribute
    from usage_limits.providers import gemini as gemini_module

    original_path = gemini_module.DEFAULT_DB_PATH
    try:
        gemini_module.DEFAULT_DB_PATH = db_path
        result = provider.fetch_raw()
        # Empty DB should return 0 count
        assert result["count"] == 0
        assert result["source"] == "local_db"
    finally:
        gemini_module.DEFAULT_DB_PATH = original_path


def test_fetch_raw_counts_todays_gemini_api_requests(tmp_path: Path) -> None:
    """fetch_raw must return the exact count of today's gemini-cli api_request logs.

    This test proves the SQL query correctly counts matching events.
    """
    db_path = tmp_path / "telemetry.db"
    _make_db(db_path)

    # Insert 3 requests for today
    with sqlite3.connect(db_path) as conn:
        _insert_log(conn, time_unix_nano=_today_nano())
        _insert_log(conn, time_unix_nano=_today_nano())
        _insert_log(conn, time_unix_nano=_today_nano())

    from usage_limits.providers import gemini as gemini_module

    original_path = gemini_module.DEFAULT_DB_PATH
    try:
        gemini_module.DEFAULT_DB_PATH = db_path
        result = GeminiProvider().fetch_raw()
        assert result["count"] == 3
        assert result["source"] == "local_db"
    finally:
        gemini_module.DEFAULT_DB_PATH = original_path


def test_fetch_raw_excludes_yesterday_logs(tmp_path: Path) -> None:
    """fetch_raw must not count logs from previous days.

    This test proves the date filtering in the SQL query works correctly.
    """
    db_path = tmp_path / "telemetry.db"
    _make_db(db_path)

    # Insert 1 for today, 1 for yesterday
    with sqlite3.connect(db_path) as conn:
        _insert_log(conn, time_unix_nano=_today_nano())
        _insert_log(conn, time_unix_nano=_yesterday_nano())

    from usage_limits.providers import gemini as gemini_module

    original_path = gemini_module.DEFAULT_DB_PATH
    try:
        gemini_module.DEFAULT_DB_PATH = db_path
        result = GeminiProvider().fetch_raw()
        assert result["count"] == 1  # Only today's
        assert result["source"] == "local_db"
    finally:
        gemini_module.DEFAULT_DB_PATH = original_path


def test_fetch_raw_excludes_wrong_service_name(tmp_path: Path) -> None:
    """fetch_raw must only count logs from service.name == 'gemini-cli'.

    This test proves the service filtering in the SQL query works correctly.
    """
    db_path = tmp_path / "telemetry.db"
    _make_db(db_path)

    # Insert logs for different services
    with sqlite3.connect(db_path) as conn:
        _insert_log(conn, time_unix_nano=_today_nano(), service_name="gemini-cli")
        _insert_log(conn, time_unix_nano=_today_nano(), service_name="openrouter")
        _insert_log(conn, time_unix_nano=_today_nano(), service_name="claude")

    from usage_limits.providers import gemini as gemini_module

    original_path = gemini_module.DEFAULT_DB_PATH
    try:
        gemini_module.DEFAULT_DB_PATH = db_path
        result = GeminiProvider().fetch_raw()
        assert result["count"] == 1  # Only gemini-cli
        assert result["source"] == "local_db"
    finally:
        gemini_module.DEFAULT_DB_PATH = original_path


def test_fetch_raw_excludes_wrong_event_name(tmp_path: Path) -> None:
    """fetch_raw must only count logs with event.name == 'gemini_cli.api_request'.

    This test proves the event name filtering in the SQL query works correctly.
    """
    db_path = tmp_path / "telemetry.db"
    _make_db(db_path)

    # Insert logs for different event types
    with sqlite3.connect(db_path) as conn:
        _insert_log(conn, time_unix_nano=_today_nano(), event_name="gemini_cli.api_request")
        _insert_log(conn, time_unix_nano=_today_nano(), event_name="gemini_cli.stream_chunk")
        _insert_log(conn, time_unix_nano=_today_nano(), event_name="gemini_cli.session_start")

    from usage_limits.providers import gemini as gemini_module

    original_path = gemini_module.DEFAULT_DB_PATH
    try:
        gemini_module.DEFAULT_DB_PATH = db_path
        result = GeminiProvider().fetch_raw()
        assert result["count"] == 1  # Only api_request events
        assert result["source"] == "local_db"
    finally:
        gemini_module.DEFAULT_DB_PATH = original_path


def test_fetch_raw_returns_zero_for_empty_db(tmp_path: Path) -> None:
    """fetch_raw returns zero count for empty database."""
    db_path = tmp_path / "telemetry.db"
    _make_db(db_path)

    from usage_limits.providers import gemini as gemini_module

    original_path = gemini_module.DEFAULT_DB_PATH
    try:
        gemini_module.DEFAULT_DB_PATH = db_path
        result = GeminiProvider().fetch_raw()
        assert result["count"] == 0
        assert result["source"] == "local_db"
    finally:
        gemini_module.DEFAULT_DB_PATH = original_path
