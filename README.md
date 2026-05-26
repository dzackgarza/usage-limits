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
  Reads the V2 account index from `~/.antigravity_cockpit/accounts.json`, resolves each
  entry to a per-account credential file under `accounts/<uuid>.json`, then refreshes
  the OAuth access token and calls the Cloud Code `loadCodeAssist` and
  `fetchAvailableModels` APIs directly.
  Supports multiple accounts — one snapshot per email.
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

- **Cursor**: Reads `state.vscdb` (VS Code global storage) to extract session tokens or
  secret material, then call the respective usage APIs.
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

## Dependency: cockpit-tools

Several providers (Antigravity, Codex, Kiro) rely on
[cockpit-tools](https://github.com/jlcodes99/cockpit-tools) — a desktop application that
manages OAuth credentials for multiple AI services.

### Why cockpit-tools?

Instead of each provider implementing its own OAuth login and token storage,
cockpit-tools acts as a centralized credential manager.
It stores refresh tokens in a well-known directory (`~/.antigravity_cockpit/`) that
`usage-limits` reads directly.

The following providers depend on cockpit-tools files:

| Provider | File(s) | Purpose |
| --- | --- | --- |
| Antigravity | `accounts.json` + `accounts/<uuid>.json` | Google OAuth refresh tokens for Google Cloud Code API |
| Codex | `codex_accounts.json` + `codex_accounts/<id>.json` | ChatGPT access tokens for WHAM usage API |
| Kiro | `kiro_accounts.json` + `kiro_accounts/<id>.json` | Kiro API tokens (partial — SQLite fallback used) |

### How to install

1. Visit
   [github.com/jlcodes99/cockpit-tools/releases](https://github.com/jlcodes99/cockpit-tools/releases)
2. Download the latest release for your platform
3. Run cockpit-tools and complete the Google OAuth login

### Adding accounts

Launch cockpit-tools and navigate to the accounts section.
Add one or more Google accounts — each goes through the OAuth consent flow.
Once added, the following files are created automatically:

```
~/.antigravity_cockpit/
  accounts.json              # V2 account index (all services)
  accounts/<uuid>.json       # Per-account OAuth credentials
  codex_accounts.json        # Codex-specific account index
  codex_accounts/<id>.json   # Per-account ChatGPT tokens
  kiro_accounts.json         # Kiro-specific account index
  kiro_accounts/<id>.json    # Per-account Kiro tokens
```

### Diagnostics

Run `usage-limits doctor` to check that cockpit-tools is installed, that account files
exist, and that tokens are present.
The doctor command provides specific remediation instructions for each issue.

## Prerequisites

- **Antigravity provider**: [cockpit-tools](https://github.com/jlcodes99/cockpit-tools)
  must be installed with at least one Google account added via the cockpit-tools UI. The
  provider discovers accounts from `~/.antigravity_cockpit/accounts.json` and reads
  OAuth refresh tokens from `~/.antigravity_cockpit/accounts/<uuid>.json` — the V2
  credential storage format written by cockpit-tools.
  Accounts whose individual file has `"disabled": true` are skipped.
  The OAuth client ID and secret are hardcoded (they match the public values embedded in
  cockpit-tools source).
- **Codex**: Requires cockpit-tools with a Codex account added, or the standard
  `~/.codex/auth.json` from `codex login`.
- **Claude Code**: Requires `claude login` to have produced
  `~/.claude/.credentials.json`.
- **Copilot**: Requires `gh auth login`.
- **Kiro**: Requires cockpit-tools with a Kiro account added, or the standard
  `~/.local/share/kiro-cli/data.sqlite3` from the Kiro CLI.
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
