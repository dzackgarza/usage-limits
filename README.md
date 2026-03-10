[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/I2I57UKJ8)

# usage-limits

Uniform quota collection and rendering for CLI- and API-backed LLM providers.

## Current Provider Coverage

| Provider | Status | Window(s) | Mechanism | Reliance |
| :--- | :--- | :--- | :--- | :--- |
| **Amp** | ✅ | Continual | `amp usage` | Local CLI |
| **Antigravity** | ✅ | Dynamic | `antigravity-usage quota` | Local CLI |
| **Claude** | ✅ | 5h, 7d | OAuth API | `~/.claude/.credentials.json` |
| **Codex** | ✅ | 5h, 7d | WHAM API | `~/.codex/auth.json` |
| **Ollama** | ✅ | 5h, 7d | HTML Scrape | `OLLAMA_SESSION_COOKIE` |
| **Qwen** | ✅ | Daily | Local Logs | `~/qwen-logs/*.json` |
| **OpenRouter** | 🛠️ | Daily | *Not Implemented* | Tracking mechanism needed |

## How It Works

### First-Party CLI Wrappers
- **Amp**: Credits replenish at a fixed rate up to $10.00. Collection parses `amp usage` text.
- **Antigravity**: Multi-model quotas (Flash, Pro, Claude, GPT-OSS). Collection parses `antigravity-usage --json`.

### Web & OAuth APIs
- **Claude Code**: Anthropic OAuth API. Relies on the JSON credentials file created by `claude login`.
- **Codex**: ChatGPT WHAM (Usage) API. Relies on the JSON auth file created by `codex login`.
- **Ollama Cloud**: Scrapes `ollama.com/settings`. Requires `OLLAMA_SESSION_COOKIE` exported in your environment.

### Local Observability
- **Qwen Code**: Free tier allows 1000 requests/day (UTC reset).
  - Requires enabling OpenAI logging in `~/.qwen/settings.json`:
    ```json
    { "model": { "enableOpenAILogging": true, "openAILoggingDir": "~/qwen-logs" } }
    ```
  - Collection counts files matching `openai-YYYY-MM-DD*.json` for the current UTC day.

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
