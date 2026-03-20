# New Providers: GitHub Copilot and Gemini CLI (OAuth)

This document describes the newly added providers for tracking usage limits.

## GitHub Copilot

### Setup

GitHub Copilot authentication is read from the shared OpenCode auth file:

**File**: `~/.local/share/opencode/auth.json`

**Expected structure**:

```json
{
  "github-copilot": "<access_token>"
}
```

Or with object format:

```json
{
  "github-copilot": {
    "access": "<access_token>"
  }
}
```

### Usage Windows

The Copilot provider tracks three quota windows:

1. **Copilot Chat** - Chat interaction quota
2. **Copilot Completions** - Code completion quota
3. **Copilot Premium** - Premium model interactions quota

All windows reset on the same date (typically monthly).

### API Endpoint

- **URL**: `GET https://api.github.com/copilot_internal/user`
- **Headers**:
  - `Authorization: token <access_token>`
  - `Editor-Version: vscode/1.96.2`
  - `X-Github-Api-Version: 2025-04-01`

### Example

```bash
usage-limits -p copilot
```

Output:

```
GitHub Copilot
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Identifier              ┃   % Used ┃ Reset At             ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ Copilot Chat            │    25.0 │ 2026-04-01 00:00 UTC │
│ Copilot Completions     │    15.0 │ 2026-04-01 00:00 UTC │
│ Copilot Premium         │    40.0 │ 2026-04-01 00:00 UTC │
└─────────────────────────┴─────────┴──────────────────────┘
```

---

## Gemini CLI (OAuth API)

### Setup

Gemini CLI now supports **two collection mechanisms**:

1. **Google OAuth API** (primary) - Direct quota from Google's API
2. **Local DB counting** (fallback) - Counts requests from otlp-collector DB

#### OAuth API Authentication

**File**: `~/.local/share/opencode/auth.json`

**Expected structure**:

```json
{
  "google": {
    "oauth": {
      "access": "<access_token>",
      "refresh": "<refresh_token>|<project_id>|<managed_project_id>",
      "expires": <timestamp>
    }
  }
}
```

### Usage Windows

The Gemini provider tracks model-specific quotas:

- **Gemini gemini-2.5-pro** - Per-model daily quota
- **Gemini gemini-2.0-flash** - Per-model daily quota
- etc.

Windows are typically **daily** (reset at midnight UTC).

### API Endpoint

- **URL**: `POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota`
- **Headers**: `Authorization: Bearer <access_token>`
- **Body**: `{ "project": "<project_id>" }` (optional)

### Fallback: Local DB Counting

If OAuth credentials are not available, the provider falls back to counting API requests from the otlp-collector SQLite database.

**Default limit**: 1000 requests/day (configurable via `DEFAULT_DAILY_LIMIT`)

### Example

```bash
usage-limits -p gemini
```

OAuth API output:

```
Gemini CLI
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Identifier              ┃   % Used ┃ Reset At             ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ Gemini gemini-2.5-pro   │    30.0 │ 2026-03-20 00:00 UTC │
│ Gemini gemini-2.0-flash │    15.0 │ 2026-03-20 00:00 UTC │
└─────────────────────────┴─────────┴──────────────────────┘
```

Local DB fallback output:

```
Gemini CLI
┏━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┓
┃ Identifier              ┃   % Used ┃ Reset At             ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━┩
│ Gemini CLI (daily)      │     5.2 │ 2026-03-20 00:00 UTC │
└─────────────────────────┴─────────┴──────────────────────┘
```

---

## Implementation Notes

### Provider Files

- **GitHub Copilot**: `src/usage_limits/providers/copilot.py`
- **Gemini CLI**: `src/usage_limits/providers/gemini.py` (updated)

### Registry Updates

Both providers are registered in:

- `src/usage_limits/providers/__init__.py`
- `src/usage_limits/registry.py`

### Testing

All providers include comprehensive tests in `tests/`:

- `tests/test_copilot_provider.py` (to be added)
- `tests/test_gemini_provider.py` (updated)

### Data Sources

Both providers follow the OpenChamber implementation patterns:

1. **GitHub Copilot**: Uses the same internal GitHub API endpoint
2. **Gemini CLI**: Uses the same Google Cloud Code API endpoint

This ensures consistency with other tools in the OpenCode ecosystem.

---

## Migration Guide

### For Existing Gemini CLI Users

If you were using the local DB counting method, no changes are needed - the provider will automatically fall back to local DB if OAuth credentials are not available.

To enable OAuth API tracking:

1. Ensure you're logged into Gemini CLI: `gemini login`
2. Verify auth file exists: `~/.local/share/opencode/auth.json`
3. Run `usage-limits -p gemini` - it will automatically use OAuth API

### For New GitHub Copilot Users

1. Configure auth in `~/.local/share/opencode/auth.json`:
   ```bash
   echo '{"github-copilot": "<your-token>"}' > ~/.local/share/opencode/auth.json
   ```
2. Run `usage-limits -p copilot`

---

## Troubleshooting

### "Not logged in" Error

Ensure the auth file exists and contains valid credentials:

```bash
cat ~/.local/share/opencode/auth.json
```

### "Authentication failed" Error

Tokens may have expired. Re-authenticate:

- **Gemini CLI**: `gemini login`
- **GitHub Copilot**: Follow your editor's Copilot auth flow

### Fallback to Local DB

If you see "Warning: OAuth API failed, falling back to local DB", check:

1. Network connectivity to Google APIs
2. Token expiration in auth file
3. Project ID configuration
