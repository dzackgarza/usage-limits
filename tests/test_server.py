from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from usage_limits.server import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_header(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    token = "test-token"
    monkeypatch.setenv("OPENROUTER_SINK_TOKEN", token)
    return {"X-OTLP-Token": token}


@pytest.fixture
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state_dir = tmp_path / ".local" / "state" / "openrouter_usage"
    state_dir.mkdir(parents=True)
    file = state_dir / "traces.json"
    monkeypatch.setattr("usage_limits.server.STATE_FILE", file)
    return file


def test_receive_traces(client: TestClient, state_file: Path, auth_header: dict[str, str]) -> None:
    # Minimal OTLP/JSON payload with 2 spans
    # IDs in OTLP/JSON must be base64-encoded bytes
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "openrouter"}}]},
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

    response = client.post("/v1/traces", json=payload, headers=auth_header)
    assert response.status_code == 200
    assert response.json() == {}

    # Verify state file was updated
    today = datetime.now(UTC).date().isoformat()
    state = json.loads(state_file.read_text())
    assert state[today] == 2


def test_status(client: TestClient, state_file: Path, auth_header: dict[str, str]) -> None:
    # Set initial state
    today = datetime.now(UTC).date().isoformat()
    state_file.write_text(json.dumps({today: 5}))

    response = client.get("/status", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["usage"][today] == 5


def test_unauthorized(client: TestClient, auth_header: dict[str, str]) -> None:
    # No header
    response = client.get("/status")
    assert response.status_code == 401

    # Wrong token
    response = client.get("/status", headers={"X-OTLP-Token": "wrong"})
    assert response.status_code == 401


def test_no_token_set_locally(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure OPENROUTER_SINK_TOKEN is NOT set
    monkeypatch.delenv("OPENROUTER_SINK_TOKEN", raising=False)
    response = client.get("/status")
    assert response.status_code == 500
    assert response.json()["detail"] == "OPENROUTER_SINK_TOKEN not set locally"
