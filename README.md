[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/I2I57UKJ8)

# usage-limits

Uniform quota collection and rendering for CLI- and API-backed LLM providers.

## Features

- Collects quota data from **9 providers**: Amp, Antigravity, Claude, Codex, GitHub Copilot, Gemini CLI, Ollama, OpenRouter, and Qwen
- **OpenChamber-aligned**: Same auth sources, API endpoints, and data parsing as OpenChamber
- **Automatic token refresh**: Gemini CLI and Claude auto-refresh expired OAuth tokens
- **Multiple collection mechanisms**: OAuth API, WHAM API, Copilot Internal API, OTLP spans/logs, HTML scraping
- **Unified JSON output** for display or downstream automation

## Current Provider Coverage

| Provider           | Status | Window(s)                  | Mechanism                          | Auth Source                         |
| :----------------- | :----- | :------------------------- | :--------------------------------- | :---------------------------------- |
| **Amp**            | ✅     | Continual                  | `amp usage` CLI                    | Local CLI                           |
| **Antigravity**    | ✅     | Dynamic (5h/daily)         | `antigravity-usage quota` CLI      | Local CLI                           |
| **Claude**         | ✅     | 5h, 7d, 7d-sonnet, 7d-opus | Anthropic OAuth API + auto-refresh | `~/.local/share/opencode/auth.json` |
| **Codex**          | ✅     | 5h, weekly                 | ChatGPT WHAM API                   | `~/.local/share/opencode/auth.json` |
| **GitHub Copilot** | ✅     | Monthly                    | GitHub Copilot Internal API        | `~/.local/share/opencode/auth.json` |
| **Gemini CLI**     | ✅     | Daily (per-model)          | Google OAuth API + auto-refresh    | `~/.local/share/opencode/auth.json` |
| **Ollama**         | ✅     | 5h, 7d                     | HTML Scrape                        | `OLLAMA_SESSION_COOKIE`             |
| **OpenRouter**     | ✅     | Daily                      | OTLP spans counting                | `~/.local/share/otlp-collector/`    |
| **Qwen**           | ✅     | Daily                      | OTLP logs counting                 | `~/qwen-logs/*.json`                |

## How It Works

### First-Party CLI Wrappers

- **Amp**: Credits replenish at a fixed rate up to $10.00. Collection parses `amp usage` text.
- **Antigravity**: Multi-model quotas (Flash, Pro, Claude, GPT-OSS). Collection parses `antigravity-usage --json`.

### Web & OAuth APIs (OpenChamber-Aligned)

- **Claude Code**: Anthropic OAuth API (`api.anthropic.com/api/oauth/usage`). Auto-refreshes tokens via `claude` CLI on 401 errors.
- **Codex**: ChatGPT WHAM API (`chatgpt.com/backend-api/wham/usage`). Shows 5h and weekly windows.
- **Gemini CLI**: Google OAuth API (`cloudcode-pa.googleapis.com`). Auto-refreshes tokens, fetches all available models.
- **GitHub Copilot**: GitHub Internal API (`api.github.com/copilot_internal/user`). Tracks chat, completions, and premium quotas.
- **Ollama Cloud**: Scrapes `ollama.com/settings`. Requires `OLLAMA_SESSION_COOKIE` in environment.

### Local Observability (OTLP Counting)

- **OpenRouter**: Counts spans from `~/.local/share/otlp-collector/telemetry.db`. Free tier: 50-1000 req/day (configurable via `OPENROUTER_DAILY_LIMIT` env var).
- **Qwen Code**: Counts logs from `~/.local/share/otlp-collector/telemetry.db`. Free tier: 1000 requests/day (UTC reset).
  - Requires enabling OpenAI logging in `~/.qwen/settings.json`:
    ```json
    { "model": { "enableOpenAILogging": true, "openAILoggingDir": "~/qwen-logs" } }
    ```

## Usage

### Simple Collection

By default, `usage-limits` collects data for all supported providers and renders a Rich table.

```bash
usage-limits
```

### JSON Output

For programmatic use or custom filtering via `jq`, use the `-j` / `--json` flag.

```bash
usage-limits --json | jq '.providers[] | {p: .provider, a: .availability}'
```

### Options

- `-p, --provider <slug>`: Collect only specified provider(s).
- `-n, --notify`: Send notifications (via local `ntfy` topic).
- `-a, --anchor`: Allow providers to "anchor" (warm up) windows (e.g., running `claude` or `ollama` with a trivial prompt).

## Setup

```bash
direnv allow
just setup
```

### Authentication

All providers (except Ollama) read credentials from the **shared OpenCode auth file**:

```bash
~/.local/share/opencode/auth.json
```

This file is automatically populated when you authenticate with each CLI:

```bash
claude login      # Claude Code
codex login       # Codex
gemini login      # Gemini CLI
# GitHub Copilot auth is set up via VS Code extension
```

### OpenRouter Setup

OpenRouter tracks usage via **OTLP spans**. Ensure your OpenRouter client emits OpenTelemetry traces to the otlp-collector:

```bash
# Optional: Set custom daily limit (default: 1000 req/day)
export OPENROUTER_DAILY_LIMIT=50  # Free tier without credits
```

## JSON Contract

The canonical JSON contract includes:

- `version`: Contract version.
- `captured_at`: UTC timestamp.
- `providers`: List of provider snapshots.

Each provider snapshot contains:

- `status`: `ok` or `error`.
- `rows`: List of usage rows (Identifier, % used, Reset time).
- `availability`: High-level summary of model readiness.
- `errors`: List of provider-specific error messages.

## Development

- `just check`: Run lint, typecheck, and tests.
- `just bump`: Increment the patch version and tag it.
- `just publish`: Push tags to trigger the PyPI publishing workflow.

## OpenChamber Alignment

This tool is aligned with [OpenChamber](https://github.com/openchamber/openchamber)'s quota implementation:

- ✅ Same auth source (`~/.local/share/opencode/auth.json`)
- ✅ Same API endpoints and request formats
- ✅ Same response parsing and data transformation
- ✅ Automatic OAuth token refresh (Gemini, Claude)
- ✅ All available models shown (via `fetchAvailableModels` endpoint)

See `docs/OPENCHAMBER_ALIGNMENT.md` for detailed alignment documentation.
