from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from google.protobuf.json_format import Parse  # type: ignore[import-untyped]
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from usage_limits.storage import TraceStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load trace store on startup."""
    app.state.store = TraceStore()
    yield


app = FastAPI(lifespan=lifespan)


def _verify_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_otlp_token: Annotated[str | None, Header(alias="X-OTLP-Token")] = None,
) -> None:
    """Verify the request token against OPENROUTER_SINK_TOKEN.
    Trusts local requests from 127.0.0.1 without a token.
    """
    if request.client and request.client.host in ("127.0.0.1", "::1"):
        return

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
    """Receive OTLP logs and store api_request events."""
    body = await request.json()
    
    store: TraceStore = request.app.state.store
    
    # Process resourceLogs (where api_request events are)
    for rl in body.get("resourceLogs", []):
        provider = "unknown"
        for attr in rl.get("resource", {}).get("attributes", []):
            if attr.get("key") == "service.name":
                provider = attr.get("value", {}).get("stringValue", "unknown")
                break
        
        if provider == "gemini-cli":
            provider = "qwen"
        
        for sl in rl.get("scopeLogs", []):
            for lr in sl.get("logRecords", []):
                # Only store api_request events
                for attr in lr.get("attributes", []):
                    if attr.get("key") == "event.name":
                        event_name = attr.get("value", {}).get("stringValue", "")
                        if event_name in ("qwen-code.api_request", "gemini_cli.api_request"):
                            store.add_trace(provider, lr)
    
    return {}


@app.get("/status", dependencies=[Depends(_verify_token)])
async def status(request: Request) -> dict[str, Any]:
    """Check the server and usage status."""
    store: TraceStore = request.app.state.store
    return {
        "status": "ok",
        "today": datetime.now(UTC).date().isoformat(),
        "usage": store.get_daily_counts(),
    }


# This is for internal JSON serialization of ExportTraceServiceRequest
import json
