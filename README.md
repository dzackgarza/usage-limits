[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/I2I57UKJ8)

# usage-limits

Uniform quota collection and rendering for CLI- and API-backed LLM providers.

## Quick start

1. Install [cockpit-tools](https://github.com/jlcodes99/cockpit-tools) and add accounts
   via the UI. This populates the OAuth tokens that Antigravity, Codex, and Kiro need.
2. Run `uvx git+https://github.com/dzackgarza/usage-limits doctor` — checks provider
   readiness and points out anything missing.
3. Run `uvx git+https://github.com/dzackgarza/usage-limits --help` — available commands
   and flags.
4. Run `uvx git+https://github.com/dzackgarza/usage-limits` — collects and displays
   usage data from all available providers.

## Provider coverage

| Provider | Strategy | How to set up |
| :--- | :--- | :--- |
| Antigravity | cockpit-tools OAuth | Install cockpit-tools, add a Google account via its UI |
| Claude Code | OAuth credential | Run `claude login` |
| Codex | OAuth credential | Run `codex login` (or add a Codex account in cockpit-tools) |
| Copilot | GitHub CLI token | Run `gh auth login` |
| Cursor | SQLite database | Have Cursor installed and logged in |
| DeepSeek | API key + balance query | Set `DEEPSEEK_API_KEY` environment variable |
| Kiro | SQLite + OAuth | Have Kiro CLI installed and logged in (or cockpit-tools) |
| Ollama Cloud | Cookie scrape | Visit ollama.com and log in via Chromium |
| OpenCode Go | Cookie scrape | Visit opencode.ai and log in via Chromium |
| OpenCode Zen | API probe | Nothing — pings a free endpoint, no auth needed |
| OpenRouter | OTLP trace sink | Start the built-in trace server with `OPENROUTER_SINK_TOKEN` set |
| Trae | SQLite database | Have Trae installed and logged in |

## Provider setup

### Antigravity

Reads OAuth refresh tokens from cockpit-tools credential files, then calls the Google
Cloud Code API (`loadCodeAssist`, `fetchAvailableModels`). Supports multiple accounts
and multi-model quotas (Flash, Pro, Claude, GPT-OSS).

- **Setup**: Install [cockpit-tools](https://github.com/jlcodes99/cockpit-tools), launch
  it, and add a Google account via its UI.
- **Files**: `~/.antigravity_cockpit/accounts.json` (account index) +
  `accounts/<uuid>.json` (per-account OAuth refresh tokens).

### Claude Code

Reads the OAuth credential file produced by `claude login`.

- **Setup**: Run `claude login` and complete the browser-based OAuth flow.
- **File**: `~/.claude/.credentials.json`

### Codex

Reads a ChatGPT WHAM API auth file, using either `codex login` or cockpit-tools account
files.

- **Setup**: Run `codex login`, or add a Codex account in cockpit-tools.
- **Files**: `~/.codex/auth.json` — or cockpit-tools
  `~/.antigravity_cockpit/codex_accounts/<id>.json`

### Copilot

Uses the GitHub OAuth token managed by `gh`.

- **Setup**: Run `gh auth login`.
- **Token**: Retrieved via `gh auth token`.

### Cursor

Reads session tokens from the VS Code global storage SQLite database, then exchanges
them for API access to Cursor's usage-summary endpoint.

- **Setup**: Install Cursor and log in.
- **Database**: `~/.config/Cursor/User/globalStorage/state.vscdb` (Linux) or equivalent
  per-platform VS Code global storage path.

### Kiro

Reads OAuth tokens from the Kiro CLI SQLite database or from cockpit-tools account
files.

- **Setup**: Install Kiro CLI and run `kiro login`, or add a Kiro account in
  cockpit-tools.
- **Files**: `~/.local/share/kiro-cli/data.sqlite3` — or cockpit-tools
  `~/.antigravity_cockpit/kiro_accounts/<id>.json`

### DeepSeek

Queries the DeepSeek `/user/balance` endpoint for prepaid account balance.

- **Setup**: Set the `DEEPSEEK_API_KEY` environment variable.
- **Note**: Silently returns no rows when the env var is unset (no error).

### Ollama Cloud

Scrapes the Ollama subscription page using a Chromium session cookie extracted via
`browser_cookie3`.

- **Setup**: Visit [ollama.com](https://ollama.com) in Chromium and log in.
  The session cookie must be present — the tool does not open a browser for you.
- **No local file to configure**: the cookie is read from the Chromium cookie store.

### OpenCode Go

Scrapes the OpenCode workspace subscription page using a Chromium session cookie.
The workspace ID is auto-discovered from `opencode.ai`.

- **Setup**: Visit [opencode.ai](https://opencode.ai) in Chromium and log in.
- **No local file to configure**: the cookie is read from the Chromium cookie store.

### OpenCode Zen

Pings the free OpenCode inference endpoint as a health check.
A successful response means the service is available.

- **Setup**: Nothing required — no auth, no local files.
- **Note**: Shows 0% used when available, errors propagate if the endpoint is down.

### OpenRouter

Usage is tracked by a built-in OTLP trace sink server that receives trace exports from
OpenRouter and writes daily request counts to a state file.

- **Setup**: Start the server with
  `uvx --from git+https://github.com/dzackgarza/usage-limits usage-limits serve`, with
  `OPENROUTER_SINK_TOKEN` set in the environment.
  Then configure OpenRouter to export OTLP traces to the server's `/v1/traces` endpoint.
- **File**: `~/.local/state/openrouter_usage/traces.json` — daily count map written by
  the sink server.
- **Note**: Inactive by default — not collected unless explicitly enabled (no server
  running = no trace data).

### Trae

Reads session tokens from the Trae global storage file, then exchanges them for API
access to Trae's usage endpoint.

- **Setup**: Install Trae and log in.
- **File**: `~/.config/Trae/User/globalStorage/storage.json` (Linux) or equivalent
  per-platform path.

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

## Development

- `just check`: Run lint, typecheck, and tests.
- `just bump`: Increment the patch version and tag it.
- `just publish`: Push tags to trigger the PyPI publishing workflow.
