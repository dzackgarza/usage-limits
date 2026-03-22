"""Tests for QwenProvider.fetch_raw correctness against real SQLite data."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from usage_limits.providers.qwen import QwenProvider


def _make_db(path: Path) -> None:
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
    service_name: str = "qwen",
    event_name: str = "qwen-code.api_request",
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
    return int(datetime.now(UTC).timestamp() * 1_000_000_000)


def _yesterday_nano() -> int:
    yesterday = datetime.now(UTC) - timedelta(days=1)
    return int(yesterday.timestamp() * 1_000_000_000)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "telemetry.db"
    _make_db(path)
    return path


def test_fetch_raw_returns_zero_when_db_missing() -> None:
    result = QwenProvider().fetch_raw(db_path=Path("/nonexistent/path/telemetry.db"))
    assert result == {"count": 0}


def test_fetch_raw_counts_todays_qwen_api_requests(db_path: Path) -> None:
    """fetch_raw must return the exact count of today's qwen api_request logs."""
    with sqlite3.connect(db_path) as conn:
        _insert_log(conn, time_unix_nano=_today_nano())
        _insert_log(conn, time_unix_nano=_today_nano())

    result = QwenProvider().fetch_raw(db_path=db_path)
    assert result["count"] == 2


def test_fetch_raw_excludes_yesterday_logs(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        _insert_log(conn, time_unix_nano=_today_nano())
        _insert_log(conn, time_unix_nano=_yesterday_nano())

    result = QwenProvider().fetch_raw(db_path=db_path)
    assert result["count"] == 1


def test_fetch_raw_excludes_wrong_service_name(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        _insert_log(conn, time_unix_nano=_today_nano(), service_name="qwen")
        _insert_log(conn, time_unix_nano=_today_nano(), service_name="gemini-cli")
        _insert_log(conn, time_unix_nano=_today_nano(), service_name="openrouter")

    result = QwenProvider().fetch_raw(db_path=db_path)
    assert result["count"] == 1


def test_fetch_raw_excludes_wrong_event_name(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        _insert_log(conn, time_unix_nano=_today_nano(), event_name="qwen-code.api_request")
        _insert_log(conn, time_unix_nano=_today_nano(), event_name="qwen-code.stream_chunk")
        _insert_log(conn, time_unix_nano=_today_nano(), event_name="qwen-code.session_start")

    result = QwenProvider().fetch_raw(db_path=db_path)
    assert result["count"] == 1


def test_fetch_raw_returns_zero_for_empty_db(db_path: Path) -> None:
    result = QwenProvider().fetch_raw(db_path=db_path)
    assert result == {"count": 0}
