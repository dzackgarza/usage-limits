[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/I2I57UKJ8)

# usage-limits

Uniform quota collection and rendering for CLI- and API-backed LLM providers.

## Current Provider Coverage

| Provider | Status | Window(s) | Mechanism | Reliance |
| :--- | :--- | :--- | :--- | :--- |
| **Antigravity** | ✅ | Dynamic | `antigravity-usage quota` | Local CLI |
| **Claude** | ✅ | 5h, 7d | OAuth API | `~/.claude/.credentials.json` |
| **Codex** | ✅ | 5h, 7d | WHAM API | `~/.codex/auth.json` |
| **Ollama** | ✅ | 5h, 7d | HTML Scrape | Chromium cookie (`ollama.com`) |
| **OpenCode** | ✅ | 5h, 7d, 30d | HTML Scrape | Chromium cookie (`opencode.ai`) |
| **OpenRouter** | ✅ | Daily | Local traces | `~/.local/state/openrouter_usage/traces.json` |

## How It Works

### First-Party CLI Wrappers

- **Antigravity**: Multi-model quotas (Flash, Pro, Claude, GPT-OSS). Collection parses
  `antigravity-usage --json`.

### Web & OAuth APIs

- **Claude Code**: Anthropic OAuth API. Relies on the JSON credentials file created by
  `claude login`.
- **Codex**: ChatGPT WHAM (Usage) API. Relies on the JSON auth file created by
  `codex login`.
- **Ollama Cloud**: Scrapes `ollama.com/settings`. Uses Chromium session cookie
  extracted via `browser-cookie3`.
- **OpenCode**: Scrapes `opencode.ai/workspace/{id}/go` for Go subscription usage.
  Uses Chromium session cookie extracted via `browser-cookie3`.
- **OpenRouter**: Reads a local traces file written by a separate telemetry pipeline
  (`~/.local/state/openrouter_usage/traces.json`). This file must be populated by an
  external mechanism that records OpenRouter request counts — see the telemetry setup
  guide if you want OpenRouter coverage.

## Discontinued Providers

The following providers were previously supported but their free tiers have been
discontinued and the providers removed:

- **Amp**: Free tier discontinued.
- **Qwen**: Free tier discontinued.

## Usage

### Simple Collection

By default, `usage-limits` collects data for all supported providers and renders a Rich
table.

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
- `-a, --anchor`: Allow providers to "anchor" (warm up) windows (e.g., running `claude`
  or `ollama` with a trivial prompt).

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
