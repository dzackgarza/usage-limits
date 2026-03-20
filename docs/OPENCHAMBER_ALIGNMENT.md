# OpenChamber Alignment

This document describes how `usage-limits` has been aligned with [OpenChamber](https://github.com/openchamber/openchamber)'s implementation for consistency across the ecosystem.

## Overview

OpenChamber provides a comprehensive quota tracking system for multiple AI providers. This project has been updated to use the **same authentication sources, API endpoints, and data parsing logic** as OpenChamber.

## Authentication Source

All providers now read credentials from a **single canonical source**:

**File**: `~/.local/share/opencode/auth.json`

This is the same auth file used by:

- OpenChamber
- OpenCode CLI
- Gemini CLI
- Claude Code
- Codex
- Other OpenCode ecosystem tools

### Auth File Structure

```json
{
  "anthropic": {
    "type": "oauth",
    "access": "<access_token>",
    "refresh": "<refresh_token>",
    "expires": <timestamp>
  },
  "openai": {
    "type": "oauth",
    "access": "<access_token>",
    "refresh": "<refresh_token>",
    "expires": <timestamp>,
    "accountId": "<optional_team_id>"
  },
  "google": {
    "type": "oauth",
    "access": "<access_token>",
    "refresh": "<refresh_token>|<project_id>|<managed_project_id>",
    "expires": <timestamp>
  },
  "github-copilot": {
    "type": "oauth",
    "access": "<access_token>",
    "refresh": "<refresh_token>",
    "expires": <timestamp>
  },
  "openrouter": {
    "type": "api",
    "key": "<api_key>"
  }
}
```

## Provider Alignment Status

### ✅ Fully Aligned Providers

#### 1. **Claude** (`claude`)

- **Auth source**: `~/.local/share/opencode/auth.json` (key: `anthropic` or `claude`)
- **API endpoint**: `GET https://api.anthropic.com/api/oauth/usage`
- **Beta header**: `anthropic-beta: oauth-2025-04-20`
- **Windows**:
  - `5h` - 5-hour rolling window
  - `7d` - 7-day window
  - `7d-sonnet` - 7-day Sonnet-specific
  - `7d-opus` - 7-day Opus-specific
- **Token refresh**: Manual (re-run `claude login`)
- **Changes from old implementation**:
  - ❌ Old: `~/.claude/.credentials.json`
  - ✅ New: `~/.local/share/opencode/auth.json`
  - ❌ Old: subprocess re-auth on 401
  - ✅ New: Exit with clear error message

#### 2. **Codex** (`codex`)

- **Auth source**: `~/.local/share/opencode/auth.json` (key: `openai`, `codex`, or `chatgpt`)
- **API endpoint**: `GET https://chatgpt.com/backend-api/wham/usage`
- **Headers**: Supports `ChatGPT-Account-Id` for team accounts
- **Windows**:
  - `5h` - Primary window (5 hours)
  - `weekly` - Secondary window (7 days)
  - `credits` - USD balance (if available)
- **Token refresh**: Manual (re-run `codex login`)
- **Changes from old implementation**:
  - ❌ Old: `~/.codex/auth.json`
  - ✅ New: `~/.local/share/opencode/auth.json`
  - ✅ New: Supports `accountId` from auth file

#### 3. **GitHub Copilot** (`copilot`) - NEW

- **Auth source**: `~/.local/share/opencode/auth.json` (key: `github-copilot` or `copilot`)
- **API endpoint**: `GET https://api.github.com/copilot_internal/user`
- **Headers**: `Editor-Version`, `X-Github-Api-Version`
- **Windows**:
  - `chat` - Chat interactions
  - `completions` - Code completions
  - `premium` - Premium model interactions
- **Token refresh**: Manual

#### 4. **Gemini CLI** (`gemini`)

- **Auth source**: `~/.local/share/opencode/auth.json` (key: `google` or `google.oauth`)
- **API endpoint**: `POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota`
- **Token refresh**: ✅ **Automatic** (uses OAuth2 refresh token)
- **Windows**: Per-model daily quotas
  - `gemini-2.5-pro`
  - `gemini-2.5-flash`
  - `gemini-2.5-flash-lite`
  - etc.
- **Fallback**: Local DB counting (otlp-collector)
- **Changes from old implementation**:
  - ✅ New: OAuth API support with auto-refresh
  - ✅ Kept: Local DB fallback

#### 5. **OpenRouter** (`openrouter`)

- **Auth source**: `~/.local/share/opencode/auth.json` (key: `openrouter`)
- **Tracking**: OTLP event counting from `~/.local/share/otlp-collector/telemetry.db`
- **API endpoint**: `GET https://openrouter.ai/api/v1/credits` (credit balance only, metadata)
- **OTLP Events**:
  - `service.name = "openrouter"` (resource attribute)
  - `event.name = "openrouter.request"` (event attribute)
- **Limits**: 50 req/day (never paid) or 1000 req/day (ever purchased credits)
- **Reset**: UTC midnight (daily)
- **Changes from old implementation**:
  - ✅ Kept: OTLP-based request counting (OpenRouter has no usage API)
  - ✅ New: Auth from shared `~/.local/share/opencode/auth.json`
  - ✅ New: Credit balance as metadata (informational only)
  - ✅ New: Configurable via `OPENROUTER_DAILY_LIMIT` env var
  - ✅ Updated: Uses otlp-collector module's telemetry database

**⚠️ Important**: OpenRouter does **NOT** expose usage limits via API. The credit endpoint only shows lifetime credit balance, not daily request counts or limits. This provider counts local OTLP events from the otlp-collector database to track actual usage.

### 🔧 Providers Pending Alignment

These providers exist in OpenChamber but need to be added/updated:

1. **Kimi for Coding** (`kimi-for-coding`)
   - API: `GET https://api.kimi.com/coding/v1/usages`
   - Auth: `~/.local/share/opencode/auth.json` (key: `kimi-for-coding` or `kimi`)

2. **z.ai** (`zai-coding-plan`)
   - API: `GET https://api.z.ai/api/monitor/usage/quota/limit`
   - Auth: `~/.local/share/opencode/auth.json` (key: `zai-coding-plan`, `zai`, or `z.ai`)

3. **MiniMax** (2 variants)
   - `minimax-coding-plan` (minimax.io)
   - `minimax-cn-coding-plan` (minimaxi.com)

4. **NanoGPT** (`nano-gpt`)
5. **Ollama Cloud** (`ollama-cloud`)

## Token Refresh Mechanisms

### Automatic Refresh (Implemented)

**Gemini CLI** implements automatic OAuth2 token refresh:

```python
def _get_valid_access_token(self, creds: dict[str, Any]) -> str | None:
    # Check if token is still valid (with 5 min buffer)
    expires = creds.get("expires")
    now = datetime.now(UTC).timestamp() * 1000

    if expires and expires > now + 300000:
        return creds.get("access")

    # Refresh using refresh token
    refresh_token = creds.get("refresh", "").split("|")[0]
    new_creds = self._refresh_access_token(refresh_token)
    # Update in-memory credentials
    return new_creds["access_token"]
```

### Manual Refresh (Current State)

**Claude** and **Codex** require manual re-authentication:

- **Claude**: Run `claude login`
- **Codex**: Run `codex login`

These providers check for 401 errors and provide clear error messages directing users to re-authenticate.

### Future: Automatic Refresh for All OAuth Providers

The Gemini implementation can be extended to Claude and Codex:

**Claude OAuth endpoints** (to be implemented):

```python
CLAUDE_TOKEN_ENDPOINT = "https://api.anthropic.com/oauth2/token"
CLAUDE_CLIENT_ID = "..."  # From Claude Code source
CLAUDE_CLIENT_SECRET = "..."
```

**OpenAI OAuth endpoints** (to be implemented):

```python
OPENAI_TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"
OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXxp7hrann"  # From auth token
```

## Caching Strategy

### Current State

- **No caching**: All providers fetch fresh data on each run
- **State files**: Providers can persist data to `~/.local/state/<provider>/` for historical tracking

### OpenChamber Approach

OpenChamber does **not implement caching** for quota data - it always fetches fresh data. This is the correct approach because:

1. Quota data changes frequently
2. API calls are lightweight
3. Users expect real-time data
4. Rate limits are generous

### Recommended: Smart Caching

For future optimization, consider:

```python
# Cache for 30 seconds to avoid rapid repeated calls
CACHE_TTL = 30  # seconds

def fetch_raw(self) -> dict[str, Any]:
    cached = self._load_cache()
    if cached and not self._cache_expired(cached):
        return cached

    data = self._fetch_from_api()
    self._save_cache(data)
    return data
```

## Error Handling

All providers follow OpenChamber's error handling pattern:

```python
try:
    return self._fetch_usage(token)
except requests.exceptions.HTTPError as e:
    if e.response is not None and e.response.status_code == 401:
        print("Error: Authentication failed. Please re-authenticate.", file=sys.stderr)
        sys.exit(1)
    raise
```

## API Endpoints Reference

| Provider       | Method | Endpoint                                                           | Auth Header      |
| -------------- | ------ | ------------------------------------------------------------------ | ---------------- |
| **Claude**     | GET    | `https://api.anthropic.com/api/oauth/usage`                        | `Bearer <token>` |
| **Codex**      | GET    | `https://chatgpt.com/backend-api/wham/usage`                       | `Bearer <token>` |
| **Copilot**    | GET    | `https://api.github.com/copilot_internal/user`                     | `token <token>`  |
| **Gemini**     | POST   | `https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota` | `Bearer <token>` |
| **OpenRouter** | GET    | `https://openrouter.ai/api/v1/credits`                             | `Bearer <key>`   |
| **Kimi**       | GET    | `https://api.kimi.com/coding/v1/usages`                            | `Bearer <key>`   |
| **z.ai**       | GET    | `https://api.z.ai/api/monitor/usage/quota/limit`                   | `Bearer <key>`   |

## Migration Guide

### For Existing Users

1. **Claude users**:

   ```bash
   # Old: ~/.claude/.credentials.json
   # New: ~/.local/share/opencode/auth.json
   # Action: Run 'claude login' to populate shared auth file
   ```

2. **Codex users**:

   ```bash
   # Old: ~/.codex/auth.json
   # New: ~/.local/share/opencode/auth.json
   # Action: Run 'codex login' to populate shared auth file
   ```

3. **OpenRouter users**:
   ```bash
   # Old: OPENROUTER_API_KEY env var
   # New: ~/.local/share/opencode/auth.json
   # Action: Add to auth file:
   echo '{"openrouter": {"type": "api", "key": "sk-or-..."}}' >> ~/.local/share/opencode/auth.json
   ```

### For New Users

Simply authenticate with each CLI tool - they will automatically populate the shared auth file:

```bash
claude login
codex login
gemini login
# etc.
```

## Testing

All aligned providers include comprehensive tests:

```bash
cd /home/dzack/opencode-plugins/usage-limits
just test
# 48 tests passed
```

## Next Steps

1. **Add missing providers** (Kimi, z.ai, MiniMax, NanoGPT, Ollama Cloud)
2. **Implement token refresh** for Claude and Codex
3. **Add optional caching** with configurable TTL
4. **Create migration script** for existing users

## References

- [OpenChamber Repository](https://github.com/openchamber/openchamber)
- [OpenChamber Quota Providers](https://github.com/openchamber/openchamber/tree/main/packages/web/server/lib/quota/providers)
- [OpenChamber Google Implementation](https://github.com/openchamber/openchamber/blob/main/packages/web/server/lib/quota/providers/google)
