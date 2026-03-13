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
    """Receive OTLP/JSON traces and deduplicate them into SQLite."""
    try:
        body = await request.json()
        otel_request = ExportTraceServiceRequest()
        Parse(json.dumps(body), otel_request)

        store: TraceStore = request.app.state.store

        for resource_span in otel_request.resource_spans:
            resource_attrs: dict[str, str] = {}
            for attr in resource_span.resource.attributes:
                v = attr.value
                if v.string_value:
                    resource_attrs[attr.key] = v.string_value
                elif v.int_value:
                    resource_attrs[attr.key] = str(v.int_value)
                elif v.HasField("array_value"):
                    # Flatten array of strings (e.g. process.command_args)
                    resource_attrs[attr.key] = " ".join(
                        s.string_value
                        for s in v.array_value.values
                        if s.string_value
                    )

            # Standard OTLP field for identifying the sender
            provider = resource_attrs.get("service.name", "unknown")

            # Refine provider if it's a gemini-cli derivative (like Qwen).
            # Check all command-related fields — command_args carries the real binary name.
            if provider == "gemini-cli":
                cmd_fields = " ".join([
                    resource_attrs.get("process.command", ""),
                    resource_attrs.get("process.command_args", ""),
                    resource_attrs.get("process.executable.name", ""),
                ]).lower()
                if "qwen" in cmd_fields:
                    provider = "qwen"
                else:
                    provider = "gemini"

            for scope_span in resource_span.scope_spans:
                # Use scope name as a fallback for provider
                if provider == "unknown" and scope_span.scope.name:
                    provider = scope_span.scope.name

                for span in scope_span.spans:
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
        "usage": store.get_daily_counts(),
    }


# This is for internal JSON serialization of ExportTraceServiceRequest
import json
