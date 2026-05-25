[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/I2I57UKJ8)

# usage-limits

Uniform quota collection and rendering for CLI- and API-backed LLM providers.

## Current Provider Coverage

| Provider | Status | Mechanism |
| :--- | :--- | :--- |
| **Antigravity** | ✅ | Google Cloud Code API via cockpit-tools credentials (`~/.antigravity_cockpit/credentials.json`) |
| **Claude Code** | ✅ | Anthropic OAuth API (`~/.claude/.credentials.json`) |
| **Codex** | ✅ | ChatGPT WHAM API (`~/.codex/auth.json`) |
| **Copilot** | ✅ | `gh auth token` → GitHub Copilot internal API |
| **Cursor** | ✅ | SQLite `state.vscdb` → JWT → Cursor usage-summary API |
| **Kiro** | ✅ | SQLite `data.sqlite3` → OAuth → Kiro usage API |
| **Ollama Cloud** | ✅ | Chromium session cookie → HTML scrape |
| **OpenCode** | ✅ | Chromium session cookie → workspace API → HTML scrape |
| **Qoder** | ✅ | SQLite `state.vscdb` → secret keys → Qoder credit API |
| **Trae** | ✅ | SQLite `storage.json` → JWT → Trae usage API |

### Inactive

These providers are registered but not collected by default:

| Provider | Mechanism |
| :--- | :--- |
| **OpenRouter** | Local traces file (`~/.local/state/openrouter_usage/traces.json`) |

## How It Works

### OAuth / First-Party API

Providers that expose a first-party usage API are called directly with credentials
obtained from local state files or OAuth refresh flows.

- **Antigravity**: Requires [cockpit-tools](https://github.com/jlcodes99/cockpit-tools)
  to be installed and logged in with at least one Google account.
  Reads credentials from `~/.antigravity_cockpit/credentials.json`, refreshes the access
  token via Google's OAuth2 endpoint, then calls the Cloud Code `loadCodeAssist` and
  `fetchAvailableModels` APIs directly.
  Supports multiple accounts — usage rows are tagged with the account email.
  Supports multi-model quotas (Flash, Pro, Claude, GPT-OSS).
- **Claude Code**: Anthropic OAuth API. Relies on the JSON credentials file created by
  `claude login`.
- **Codex**: ChatGPT WHAM (Usage) API. Relies on the JSON auth file created by
  `codex login`.
- **Copilot**: Uses `gh auth token` for GitHub authentication, then calls the Copilot
  internal user API.

### SQLite-Backed Credentials

Several IDE-based providers store credentials in local SQLite databases that are read
and exchanged for API tokens.

- **Cursor, Qoder**: Read `state.vscdb` (VS Code global storage) to extract session
  tokens or secret material, then call the respective usage APIs.
- **Kiro**: Reads `data.sqlite3` from the Kiro CLI state directory.
- **Trae**: Reads `storage.json` from the Trae global storage directory.

### Cookie-Based Scraping

Platforms that do not expose a usage API are scraped via Chromium session cookies
extracted with `browser_cookie3`.

- **Ollama Cloud**: Scrapes `ollama.com/settings`.
- **OpenCode**: Discovers the workspace ID from `opencode.ai`, then scrapes the
  subscription page.

## Caching

All providers have a per-provider TTL on cached fetch results (default 0 — no caching).
Claude Code is configured with a 300s TTL.

The caching layer:
- Writes every successful `fetch_raw` result to a JSON cache file in the provider's
  state directory.
- Falls back to stale cached data when a live fetch fails (transient errors, rate
  limits).
- Caches fetch failures themselves — if a provider is rate-limited, the error is
  persisted so subsequent calls within the TTL window skip the API entirely instead of
  retrying immediately.

## Prerequisites

- **Antigravity provider**: [cockpit-tools](https://github.com/jlcodes99/cockpit-tools)
  must be installed and you must be logged in to at least one Google account via the
  cockpit-tools UI. The provider reads all accounts from
  `~/.antigravity_cockpit/credentials.json` and reports quota for each.
  `ANTIGRAVITY_OAUTH_CLIENT_ID` and `ANTIGRAVITY_OAUTH_CLIENT_SECRET` must be set in
  `.envrc`.
- **Claude Code**: Requires `claude login` to have produced
  `~/.claude/.credentials.json`.
- **Codex**: Requires `codex login`.
- **Copilot**: Requires `gh auth login`.
- **Ollama Cloud / OpenCode**: Requires Chromium session cookies for the respective
  domains.

## Usage

### Simple Collection

```bash
usage-limits
```

### JSON Output

```bash
usage-limits --json | jq '.providers[] | {p: .provider, a: .availability}'
```

### Options

- `-p, --provider <slug>`: Collect only specified provider(s).
- `-j, --json`: JSON output.
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
- `status`: `ok` or `error` or `rate_limited`.
- `rows`: List of usage rows (Identifier, % used, Reset time).
- `availability`: High-level summary of model readiness.
- `errors`: List of provider-specific error messages.

## Development

- `just check`: Run lint, typecheck, and tests.
- `just bump`: Increment the patch version and tag it.
- `just publish`: Push tags to trigger the PyPI publishing workflow.
