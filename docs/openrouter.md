# OpenRouter Usage Tracking via OTLP Sink

OpenRouter does not expose free-tier request counts via its API. To provide a reliable "Source of Truth," this project relies on the [`otlp-collector`](https://github.com/dzackgarza/opencode-plugins/tree/main/otlp-collector) package — a separate OTLP sink server that receives telemetry directly from OpenRouter.

## How it Works

1.  **Out-of-Band Telemetry**: OpenRouter has a built-in "Broadcast" feature that sends a trace every time a request is made.
2.  **OTLP Sink**: `otlp-collector serve` starts a server that listens for these traces and stores them in a local SQLite database at `~/.local/state/otlp-collector/traces.db`.
3.  **Reporting**: `usage-limits -p openrouter` reads the key details from the OpenRouter API (tier and credit status) to determine which daily limit applies.

## Setup Instructions

### 1. Install and configure `otlp-collector`

Follow the setup instructions in the `otlp-collector` package. It requires `OPENROUTER_SINK_TOKEN` to be set in your environment (via `.envrc` or `.env`).

### 2. Start the Sink

Start the OTLP receiver on your local machine via the justfile recipe:

```bash
just serve
```

This runs `otlp-collector serve --port 4318`.

### 3. Expose the Sink to the Internet

OpenRouter needs a public URL to send traces to. Since the sink is local, you must use a tunnel.

**Note on Firewall/UFW**: You do **not** need to open port `4318` in `ufw`. Tunneling tools use outbound connections to establish a reverse proxy, bypassing ingress firewall rules.

Example using `localtunnel`:
```bash
npx localtunnel --port 4318
```

### 4. Configure OpenRouter

1.  Navigate to [OpenRouter Observability Settings](https://openrouter.ai/settings/observability).
2.  **Enable Broadcast**: Set to "On".
3.  **OTLP HTTP Endpoint**: Enter your public tunnel URL + `/v1/traces` (e.g., `https://nice-terms-lead.loca.lt/v1/traces`).
4.  **Custom Headers**: Add `X-OTLP-Token` with your `OPENROUTER_SINK_TOKEN` value.

## Security

*   **Authentication**: The sink denies any request without a valid `X-OTLP-Token` or `Authorization` header.
*   **Fail-Safe**: If `OPENROUTER_SINK_TOKEN` is not set in the environment, the server refuses all requests (500 Error).
*   **Minimal Surface**: The server only implements two endpoints: `POST /v1/traces` and `GET /status`.
