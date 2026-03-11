from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from google.protobuf.json_format import Parse
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

app = FastAPI()

# State management
STATE_DIR = Path.home() / ".local" / "state" / "openrouter_usage"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "traces.json"


def load_state() -> dict[str, int]:
    """Load the daily trace counts from disk."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state: dict[str, int]) -> None:
    """Save the daily trace counts to disk."""
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def increment_usage(date_str: str, count: int = 1) -> None:
    """Increment the trace count for a given date."""
    state = load_state()
    state[date_str] = state.get(date_str, 0) + count
    save_state(state)


@app.post("/v1/traces")
async def receive_traces(request: Request) -> dict[str, str]:
    """Receive OTLP/JSON traces and count them as OpenRouter requests."""
    try:
        body = await request.json()
        # Parse the OTLP/JSON into a structured request object
        # This validates the schema and ensures it's a valid OTLP trace
        otel_request = ExportTraceServiceRequest()
        Parse(json.dumps(body), otel_request)

        # Count the number of spans in the request
        # Each span from OpenRouter corresponds to one model request
        span_count = 0
        for resource_span in otel_request.resource_spans:
            for scope_span in resource_span.scope_spans:
                span_count += len(scope_span.spans)

        if span_count > 0:
            today = datetime.now(UTC).date().isoformat()
            increment_usage(today, span_count)

        return {}
    except Exception as e:
        # Standard OTLP behavior: return 400 on malformed requests
        # but the spec says receivers should be lenient
        return {"error": str(e)}


@app.get("/status")
async def status() -> dict[str, Any]:
    """Check the server and usage status."""
    return {
        "status": "ok",
        "today": datetime.now(UTC).date().isoformat(),
        "usage": load_state(),
    }
