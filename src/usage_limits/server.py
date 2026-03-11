from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from google.protobuf.json_format import Parse  # type: ignore[import-untyped]
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

# Canonical paths for state persistence
STATE_DIR = Path.home() / ".local" / "state" / "openrouter_usage"
STATE_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = STATE_DIR / "usage.db"


def get_db_path() -> Path:
    """Resolve the database path dynamically."""
    return DB_FILE


class TraceStore:
    """Manages OTLP traces in a lightweight SQLite database."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_db_path()
        self._init_db()

    def _init_db(self) -> None:
        """Create the traces table if it does not exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    raw_json JSON,
                    PRIMARY KEY (trace_id, span_id)
                )
                """
            )
            # Index for fast daily counts
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captured_at ON traces(captured_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_provider ON traces(provider)")

    def add_trace(
        self,
        trace_id: str,
        span_id: str,
        provider: str,
        raw_json: dict[str, Any],
    ) -> bool:
        """Add a trace to the database, deduplicating by trace_id + span_id."""
        captured_at = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO traces (trace_id, span_id, provider, captured_at, raw_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (trace_id, span_id, provider, captured_at, json.dumps(raw_json)),
                )
                return True
            except sqlite3.IntegrityError:
                # Already exists (deduplicated)
                return False

    def get_daily_counts(self, provider: str | None = None) -> dict[str, int]:
        """Return counts of traces per day for the given provider."""
        query = """
            SELECT date(captured_at) as day, count(*)
            FROM traces
        """
        params: list[str] = []
        if provider:
            query += " WHERE provider = ?"
            params.append(provider)
        query += " GROUP BY day"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            return {row[0]: row[1] for row in cursor.fetchall()}

    def prune_old_traces(self, days: int = 7) -> None:
        """Optional: prune traces older than X days to keep DB size small."""
        limit = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM traces WHERE captured_at < ?", (limit,))

    def save(self) -> None:
        """No-op for SQLite as it's persisted per-transaction."""
        pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load trace store on startup."""
    app.state.store = TraceStore()
    yield


app = FastAPI(lifespan=lifespan)


def _verify_token(
    authorization: Annotated[str | None, Header()] = None,
    x_otlp_token: Annotated[str | None, Header(alias="X-OTLP-Token")] = None,
) -> None:
    """Verify the request token against OPENROUTER_SINK_TOKEN."""
    token = os.environ.get("OPENROUTER_SINK_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="OPENROUTER_SINK_TOKEN not set locally")

    received = x_otlp_token
    if authorization and authorization.startswith("Bearer "):
        received = authorization[len("Bearer ") :]
    elif authorization:
        received = authorization

    if received != token:
        raise HTTPException(status_code=401, detail="Invalid or missing OTLP token")


@app.post("/v1/traces", dependencies=[Depends(_verify_token)])
async def receive_traces(request: Request) -> dict[str, str]:
    """Receive OTLP/JSON traces and deduplicate them into SQLite."""
    try:
        body = await request.json()
        otel_request = ExportTraceServiceRequest()
        Parse(json.dumps(body), otel_request)

        store: TraceStore = request.app.state.store

        for resource_span in otel_request.resource_spans:
            resource_attrs = {
                attr.key: attr.value.string_value for attr in resource_span.resource.attributes
            }
            provider = resource_attrs.get("service.name", "unknown")

            for scope_span in resource_span.scope_spans:
                # Use scope name as a fallback for provider
                if provider == "unknown" and scope_span.scope.name:
                    provider = scope_span.scope.name

                for span in scope_span.spans:
                    # We only care about openrouter traces for now
                    if provider == "openrouter":
                        store.add_trace(
                            trace_id=span.trace_id,
                            span_id=span.span_id,
                            provider=provider,
                            raw_json=body,
                        )

        return {}
    except Exception as e:
        return {"error": str(e)}


@app.get("/status", dependencies=[Depends(_verify_token)])
async def status(request: Request) -> dict[str, Any]:
    """Check the server and usage status."""
    store: TraceStore = request.app.state.store
    return {
        "status": "ok",
        "today": datetime.now(UTC).date().isoformat(),
        "usage": store.get_daily_counts(provider="openrouter"),
    }
