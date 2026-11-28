[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/I2I57UKJ8)

# usage-limits

Uniform quota collection and rendering for CLI- and API-backed LLM providers.

## Quick start

Install the CLI with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install git+https://github.com/dzackgarza/usage-limits
```

1. Run `usage-limits --help` to discover commands and flags, and
   `usage-limits providers list --json` to discover provider slugs and their default activation status.
2. Set up the providers you intend to use according to the table below. For
   app-managed OAuth, run a named login command, e.g. `usage-limits login claude`.
   `usage-limits login --help` lists the supported login subcommands; other providers
   use external CLIs, local files, or environment variables.
3. Run `usage-limits doctor` for local credential and prerequisite checks and setup hints.
   This is not a live quota check or proof that an API credential will work.
4. Run `usage-limits --provider claude` to collect a single configured provider,
   or `usage-limits` to collect all default-active providers. Add `--json` for the
   same collection as structured data (including per-provider status and errors).

For a one-off invocation without installing the tool, use
`uvx --from git+https://github.com/dzackgarza/usage-limits usage-limits --help`.

For old `cockpit-tools` credentials, use `usage-limits migrate antigravity` or
`usage-limits migrate codex`; `usage-limits migrate --help` lists the available migrations.

The `usage-limits` CLI is the primary interface. Its root command collects usage;
named subcommands handle setup, inspection and the trace server. For example,
`usage-limits providers list --help` shows the options for that command. Integrations should use the
collection's `--json` output rather than scraping the rendered table or duplicating
provider authentication and collection logic.

## Provider coverage

Collection displays each provider's result separately.
Failed providers show the original error type and message with no usage rows; successful providers remain visible.
This applies to failures during a provider's collection. Errors before collection
(for example, an unknown provider slug) can terminate the command. Check the
provider status in JSON output; a command that returns a collection can contain
failed providers. Missing credentials are not equivalent to zero usage.

The table includes registered providers, not just those collected by default.
Use `usage-limits --provider <slug>` to explicitly select a provider whose `active`
field in `usage-limits providers list --json` is false.

| Provider | Strategy | How to set up |
| :--- | :--- | :--- |
| Antigravity | Local OAuth | Run `usage-limits login antigravity` |
| Agy Secret Pool | Archived; inactive by default | Run `usage-limits --provider agy-secret-pool` to collect explicitly |
| Claude Code | App-owned subscription OAuth | Run `usage-limits login claude` |
| Codex | Local OAuth | Run `usage-limits login codex` (or `codex login`) |
| ChatGPT Pro | Estimated message counts from ChatGPT history | Run `codex login`, then `usage-limits` |
| Copilot | GitHub CLI token | Run `gh auth login` |
| Cursor | SQLite database | Have Cursor installed and logged in |
| DeepSeek | API key + balance query | Set `DEEPSEEK_API_KEY` environment variable |
| Freebuff | CLI profile / credential store | Log in through the Freebuff CLI; install Bun for keychain-backed profiles |
| Kiro | SQLite | Have Kiro CLI installed and logged in |
| Ollama Cloud | Cookie scrape | Visit ollama.com and log in via Chromium |
| OpenCode Go | Cookie scrape | Visit opencode.ai and log in via Chromium |
| OpenCode Zen | API probe | Nothing — pings a free endpoint, no auth needed |
| OpenMath | OpenMath session | Run `usage-limits login openmath` |
| OpenRouter | OTLP trace sink | Start the built-in trace server with `OPENROUTER_SINK_TOKEN` set |
| Trae | SQLite database | Have Trae installed and logged in |

## Provider setup

### Antigravity

Reads OAuth refresh tokens from the internal credential store, then calls the Google Cloud Code API (`loadCodeAssist`, then project-scoped `retrieveUserQuotaSummary`). Supports multiple accounts and AGY's Gemini vs. Claude/GPT quota pools.

- **Setup**: Run `usage-limits login antigravity` and complete the Google OAuth login.

- **Files**: `~/.config/usage-limits/credentials/antigravity/<account>.json`

### Claude Code

Uses its own OAuth login and refresh token to read Claude subscription usage.
The saved reset count comes from the reset grant block in the OAuth usage response.
`available_count` counts active, unpaused grants; `applicable_now_count` counts grants
the service marks `usable_now`. The grant block requires the Claude Code client surface and may change with that private API.

- **Setup**: Run `usage-limits login claude` and complete the browser-based OAuth flow.

- **File**: `~/.config/usage-limits/credentials/claude/default.json`

### Codex

Reads a ChatGPT WHAM API auth file, using either `usage-limits login codex` or the `codex login` command.
The WHAM response reports saved reset credits for each active account.
`available_count` is the held count; `applicable_now_count` is the count that
would restore a usage window now.

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

The archived provider reads the second, independently-metered Gemini quota pool on production `cloudcode-pa` with the same Antigravity credentials.
It is inactive by default.
Run `usage-limits --provider agy-secret-pool` to collect it explicitly.

- **Files**: shares `~/.config/usage-limits/credentials/antigravity/<account>.json`

### Kiro

Reads OAuth tokens from the Kiro CLI SQLite database.

- **Setup**: Install Kiro CLI and run `kiro login`.

- **Files**: `~/.local/share/kiro-cli/data.sqlite3`

### DeepSeek

Queries the DeepSeek `/user/balance` endpoint for prepaid account balance.

- **Setup**: Set the `DEEPSEEK_API_KEY` environment variable.

- **Note**: An unset `DEEPSEEK_API_KEY` raises `KeyError`; the collection reports a provider error, not an empty successful balance. Set the key before running `usage-limits --provider deepseek`.

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

### OpenMath

Run `usage-limits login openmath` and approve the sign-in through SAIR in your
browser. The command waits for OpenMath to confirm authorization, then saves the
session to `~/.config/usage-limits/credentials/openmath/default.json`.
Run the same command again to replace an expired or revoked session.

`usage-limits --provider openmath` uses that saved session to collect usage.
`OPENMATH_SESSION_TOKEN` and `OPENMATH_TOKEN`, when set, override the saved session.

### OpenRouter

Usage is tracked by a built-in OTLP trace sink server that receives trace exports from OpenRouter and writes daily request counts to a state file.

- **Setup**: Start the server with `usage-limits serve`, with `OPENROUTER_SINK_TOKEN` set in the environment.
  Then configure OpenRouter to export OTLP traces to the server's `/v1/traces` endpoint.

- **File**: `~/.local/state/openrouter_usage/traces.json` — daily count map written by the sink server.

- **Note**: Inactive by default — not collected unless explicitly enabled (no server running = no trace data).

### Trae

Reads session tokens from the Trae global storage file, then exchanges them for API access to Trae's usage endpoint.

- **Setup**: Install Trae and log in.

- **File**: `~/.config/Trae/User/globalStorage/storage.json` (Linux) or equivalent per-platform path.

## Caching

All providers have a per-provider TTL on cached fetch results. The default is
0 seconds (always fetch; results are still persisted). Claude Code and ChatGPT Pro
use a 300-second TTL.

The caching layer:

- Writes every successful `fetch_raw` result to a JSON cache file in the provider's state directory (separate per account for account-scoped providers).

- Reuses a successful cached result only while it is within a positive TTL. Otherwise it attempts a fresh fetch; a failed live fetch never falls back to stale quota data.

- Persists live-fetch failures as error-only cache entries, discarding any previous raw data and propagating the failure to the caller. An error-only entry is always a cache miss, even within the TTL; the next collection attempts a fresh fetch. This describes the shared cache, not provider-specific OAuth refresh or request cooldown behavior.

Successful Claude and Codex snapshots show the saved reset count below their usage
table, followed by the provider's usage page URL when a reset applies now.
JSON output puts `available_count`, `applicable_now_count`, and `usage_url` in
`providers[].saved_resets`; `null` means that
the provider did not report a saved reset inventory, while a reported zero is a
known empty inventory. These are saved one-time resets, separate from scheduled
usage-window refresh times.

## Development

- `just check`: Run lint, typecheck, and tests.

- `just bump`: Increment the patch version and tag it.

- `just publish`: Push tags to trigger the PyPI publishing workflow.
