[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/I2I57UKJ8)

# usage-limits

Uniform quota collection and rendering for CLI- and API-backed LLM providers.

## Quick start

1. Run `uvx git+https://github.com/dzackgarza/usage-limits login <provider>` for any providers you wish to connect (e.g., `antigravity`, `codex`).

2. Run `uvx git+https://github.com/dzackgarza/usage-limits doctor` — checks provider readiness and points out anything missing.

3. Run `uvx git+https://github.com/dzackgarza/usage-limits --help` — available commands and flags.

4. Run `uvx git+https://github.com/dzackgarza/usage-limits` — collects and displays usage data from all available providers.

*(If you were previously using `cockpit-tools` for authentication, run `usage-limits migrate` to copy your existing credentials over.)*

## Provider coverage

Collection displays each provider's result separately.
Failed providers show the original error type and message with no usage rows; successful providers remain visible.

| Provider | Strategy | How to set up |
| :--- | :--- | :--- |
| Antigravity | Local OAuth | Run `usage-limits login antigravity` |
| Agy Secret Pool | Local OAuth (shares Antigravity) | Run `usage-limits login antigravity` |
| Claude Code | App-owned subscription OAuth | Run `usage-limits login claude` |
| Codex | Local OAuth | Run `usage-limits login codex` (or `codex login`) |
| ChatGPT Pro | Estimated message counts from ChatGPT history | Run `codex login`, then `usage-limits` |
| Copilot | GitHub CLI token | Run `gh auth login` |
| Cursor | SQLite database | Have Cursor installed and logged in |
| DeepSeek | API key + balance query | Set `DEEPSEEK_API_KEY` environment variable |
| Kiro | SQLite | Have Kiro CLI installed and logged in |
| Ollama Cloud | Cookie scrape | Visit ollama.com and log in via Chromium |
| OpenCode Go | Cookie scrape | Visit opencode.ai and log in via Chromium |
| OpenCode Zen | API probe | Nothing — pings a free endpoint, no auth needed |
| OpenRouter | OTLP trace sink | Start the built-in trace server with `OPENROUTER_SINK_TOKEN` set |
| Trae | SQLite database | Have Trae installed and logged in |

## Provider setup

### Antigravity

Reads OAuth refresh tokens from the internal credential store, then calls the Google Cloud Code API (`loadCodeAssist`, then project-scoped `retrieveUserQuotaSummary`). Supports multiple accounts and AGY's Gemini vs. Claude/GPT quota pools.

- **Setup**: Run `usage-limits login antigravity` and complete the Google OAuth login.

- **Files**: `~/.config/usage-limits/credentials/antigravity/<account>.json`

### Claude Code

Uses its own OAuth login and refresh token to read Claude subscription usage.

- **Setup**: Run `usage-limits login claude` and complete the browser-based OAuth flow.

- **File**: `~/.config/usage-limits/credentials/claude/default.json`

### Codex

Reads a ChatGPT WHAM API auth file, using either `usage-limits login codex` or the `codex login` command.

- **Setup**: Run `usage-limits login codex` (for multi-account support) or `codex login`.

- **Files**: `~/.config/usage-limits/credentials/codex/<account>.json` and fallback to `~/.codex/auth.json`.

### ChatGPT Pro

Run `usage-limits` to collect ChatGPT Pro alongside the other active providers.
Use `usage-limits --provider chatgpt-pro` to collect it alone.
It follows the accounting observations in [CodexBar issue 3436](https://github.com/steipete/CodexBar/issues/3436).

The meter counts completed Pro assistant messages across active, archived, and Project conversations.
A send can produce several completed assistant records.
The displayed range runs from strongly grouped interactions to raw final records.
Grouping requires a shared user turn, exchange, model, active branch, and serial tool continuation.
JSON metadata includes the corresponding remaining range.
These are history estimates.
Deleted, temporary, and unavailable chats can leave gaps.
A history count alone never marks the allowance exhausted.

The default cap is an **assumption** from the issue's Pro plan sample.
Set the cap for your plan in `~/.config/usage-limits/config.toml`:

```toml
[chatgpt_pro]
weekly_limit = 50
# auth_file = "/path/to/codex/auth.json"
```

The window is a provisional rolling week.
A reported Pro model reset anchors the window end; the seven-day span remains an assumption.
A future Pro model limit reported by the server marks access blocked and supplies the reset display.
Empty initialization data does not supply an exact remaining balance.
The JSON output states the window and cap assumptions.

Credentials come from `$CODEX_HOME/auth.json`, or `~/.codex/auth.json` when `CODEX_HOME` is unset.
Only ChatGPT login mode is supported.
On an HTTP 401, the provider rereads a changed credential for the same account and retries once.
Run `codex login` if the credential needs renewal.

Conversation contents enter the process during collection.
Persistent state contains salted identifiers, timestamps, model and grouping data, and reset observations.
The ledger is scoped to the authenticated account under `~/.local/state/chatgpt_pro_usage/`. Only changed conversations are fetched again.
Later collections stop history pagination at the last successful observation.
Successful collections are cached for five minutes.
Requests are spaced and bounded; HTTP 429 starts a cooldown.
Collection errors leave the ledger intact and report unavailable usage.

### Freebuff

Reads the CLI profile at `~/.config/manicode/credentials.json`. Profiles with `tokenStore = "keychain"` use Bun's native credential-store API with the same service and profile path as the Freebuff CLI. Install Bun for those profiles.
On headless Linux, the lookup connects to the login user's systemd session bus.
File-backed profiles read their `authToken` directly.
Tokens remain in their existing store.

### Copilot

Uses the GitHub OAuth token managed by `gh`.

- **Setup**: Run `gh auth login`.

- **Token**: Retrieved via `gh auth token`.

### Cursor

Reads session tokens from the VS Code global storage SQLite database, then exchanges them for API access to Cursor's usage-summary endpoint.

- **Setup**: Install Cursor and log in.

- **Database**: `~/.config/Cursor/User/globalStorage/state.vscdb` (Linux) or equivalent per-platform VS Code global storage path.

### Agy Secret Pool

Surfaces a second, independently-metered Gemini quota pool that lives on production `cloudcode-pa` and is reachable with the same Antigravity credentials.
The Antigravity CLI enforces against its daily-channel host, so this pool sits unused by `agy` but is fully usable for direct inference — it shows up here as spare capacity.

- **Setup**: None beyond `usage-limits login antigravity` — it reuses those credentials.

- **Files**: shares `~/.config/usage-limits/credentials/antigravity/<account>.json`

### Kiro

Reads OAuth tokens from the Kiro CLI SQLite database.

- **Setup**: Install Kiro CLI and run `kiro login`.

- **Files**: `~/.local/share/kiro-cli/data.sqlite3`

### DeepSeek

Queries the DeepSeek `/user/balance` endpoint for prepaid account balance.

- **Setup**: Set the `DEEPSEEK_API_KEY` environment variable.

- **Note**: Silently returns no rows when the env var is unset (no error).

### Ollama Cloud

Scrapes the Ollama subscription page using a Chromium session cookie extracted via `browser_cookie3`.

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

Usage is tracked by a built-in OTLP trace sink server that receives trace exports from OpenRouter and writes daily request counts to a state file.

- **Setup**: Start the server with `uvx --from git+https://github.com/dzackgarza/usage-limits usage-limits serve`, with `OPENROUTER_SINK_TOKEN` set in the environment.
  Then configure OpenRouter to export OTLP traces to the server's `/v1/traces` endpoint.

- **File**: `~/.local/state/openrouter_usage/traces.json` — daily count map written by the sink server.

- **Note**: Inactive by default — not collected unless explicitly enabled (no server running = no trace data).

### Trae

Reads session tokens from the Trae global storage file, then exchanges them for API access to Trae's usage endpoint.

- **Setup**: Install Trae and log in.

- **File**: `~/.config/Trae/User/globalStorage/storage.json` (Linux) or equivalent per-platform path.

## Caching

All providers have a per-provider TTL on cached fetch results (default 0 — no caching).
Claude Code is configured with a 300s TTL.

The caching layer:

- Writes every successful `fetch_raw` result to a JSON cache file in the provider's state directory.

- Falls back to stale cached data when a live fetch fails (transient errors, rate limits).

- Caches fetch failures themselves — if a provider is rate-limited, the error is persisted so subsequent calls within the TTL window skip the API entirely instead of retrying immediately.

## Development

- `just check`: Run lint, typecheck, and tests.

- `just bump`: Increment the patch version and tag it.

- `just publish`: Push tags to trigger the PyPI publishing workflow.
