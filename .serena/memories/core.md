# usage-limits

Python tool/library for tracking and reporting usage quotas for AI models/services
(Anthropic, OpenAI, OpenRouter, GitHub Copilot, etc.). Provides unified interface:
fetch raw data → normalize → render as rich table or fire ntfy notifications.

## Source map

- `src/usage_limits/` — main package
  - `base.py` — `UsageProvider` ABC with fetch_raw/to_rows/collect_snapshot/ntfy
  - `contracts.py` — pydantic models: `UsageRow`, `ProviderSnapshot`, `UsageCollection`, etc.
  - `table.py` — `UsageTable` renderer (rich), `UsageRow`/`ModelAvailability` pydantic models
  - `registry.py` — provider discovery (builtin + entry points), error normalization
  - `cli.py` — typer CLI entrypoints (one per provider + `usage-limits` umbrella)
  - `rendering.py` — collection-level rendering (aggregated tables, JSON)
  - `server.py` — FastAPI OTLP sink server for OpenRouter
  - `providers/` — one module per provider

- `tests/` — pytest suite (one test file per provider + CLI/registry/server)
  - `fixtures/` — captured real API responses for testing (not mocks)

## Key invariants

- Every provider is a class inheriting `UsageProvider` with `slug`, `name`, `state_dir`.
- No try/except, no fallback defaults, no `.get(key, default)` — crash on missing data.
- No mocks in tests — use captured real responses only.
- Type-checked with mypy strict; linted with ruff.
- `dict[str, Any]` is banned for structured data — use TypedDict or pydantic models.

## See also

- `mem:tech_stack` — dependencies, build tooling
- `mem:conventions` — code style, patterns, banned patterns
- `mem:task_completion` — test/lint/typecheck commands
- `mem:suggested_commands` — frequently used just/CLI commands
