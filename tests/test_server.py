from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from usage_limits.server import app


@pytest.fixture
def auth_header(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    token = "test-token"
    monkeypatch.setenv("OPENROUTER_SINK_TOKEN", token)
    return {"X-OTLP-Token": token}


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / ".local" / "state" / "openrouter_usage"
    directory.mkdir(parents=True)
    file = directory / "usage.db"
    monkeypatch.setattr("usage_limits.server.DB_FILE", file)
    monkeypatch.setattr("usage_limits.server.get_db_path", lambda: file)
    return file


def test_receive_traces(db_path: Path, auth_header: dict[str, str]) -> None:
    # Minimal OTLP/JSON payload with 2 spans
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "openrouter"}}]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {"name": "request1", "spanId": "AQ==", "traceId": "AQ=="},
                            {"name": "request2", "spanId": "Ag==", "traceId": "AQ=="},
                        ]
                    }
                ],
            }
        ]
    }

    with TestClient(app) as client:
        response = client.post("/v1/traces", json=payload, headers=auth_header)
        assert response.status_code == 200
        assert response.json() == {}

    # Verify SQLite DB was updated
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute("SELECT count(*) FROM traces")
        assert cursor.fetchone()[0] == 2


def test_status(db_path: Path, auth_header: dict[str, str]) -> None:
    # Set initial state in DB
    # We must init the DB first since we're inserting before TestClient starts
    from usage_limits.server import TraceStore

    TraceStore(db_path=db_path)

    today = datetime.now(UTC).date().isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO traces (trace_id, span_id, provider, captured_at, raw_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("t1", "s1", "openrouter", today + "T12:00:00Z", "{}"),
        )

    with TestClient(app) as client:
        response = client.get("/status", headers=auth_header)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["usage"][today] == 1


def test_unauthorized(db_path: Path, auth_header: dict[str, str]) -> None:
    with TestClient(app) as client:
        # No header
        response = client.get("/status")
        assert response.status_code == 401

        # Wrong token
        response = client.get("/status", headers={"X-OTLP-Token": "wrong"})
        assert response.status_code == 401


def test_no_token_set_locally(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure OPENROUTER_SINK_TOKEN is NOT set
    monkeypatch.delenv("OPENROUTER_SINK_TOKEN", raising=False)
    with TestClient(app) as client:
        response = client.get("/status")
        assert response.status_code == 500
        assert response.json()["detail"] == "OPENROUTER_SINK_TOKEN not set locally"
