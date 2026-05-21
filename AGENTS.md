# AGENTS.md

## Project Overview

`usage-limits` is a Python-based tool and library for tracking and reporting usage
quotas for various AI models and services (e.g., Anthropic, OpenAI, OpenRouter, GitHub
Copilot). It provides a unified interface for fetching raw usage data, converting it to
normalized usage rows, and rendering these as human-readable tables or firing
notifications (via `ntfy`) when limits are reached.

## Tech Stack

- **Language:** Python 3.12+
- **Dependency Management:** `uv`
- **Testing:** `pytest`
- **Linting/Formatting:** `ruff`
- **Type Checking:** `mypy`
- **CLI Framework:** Built-in `argparse` with `rich` for rendering.

## Code Conventions

- Follow standard Python conventions (PEP 8).
- Use `ruff` for all formatting and linting.
- Prefer type hints for all function signatures and class members.
- Providers should inherit from `UsageProvider` in `src/usage_limits/base.py`.
- New providers should be added to `src/usage_limits/providers/` and registered in
  `src/usage_limits/registry.py`.

## Testing Requirements

### Mandatory rules

- **Every provider must have a test.** A provider with no test is assumed broken until
  proven otherwise. The test must exercise `fetch_raw` + `to_rows` against a captured
  real response or verified fixture.
- **No silent fallthrough.** `to_rows` must never use `.get(key, default)` with a
  default that is indistinguishable from valid low-usage data.
  If a key is missing from `fetch_raw` output, that is a parse error — fail explicitly,
  do not default to `0.0` or `[]`.
- **No syntax-only rendering tests.** Constructing a `UsageRow` by hand and asserting it
  renders is not a provider test.
  It tests rich, not the repository.
  Every provider test must pass real or captured API output through the provider's
  parsing logic.
- **No coverage theater.** A passing test suite with zero provider coverage is fraud.
  Each provider's test must prove the provider produces correct rows from real-world
  representative input, not just that the framework doesn't crash.
- **Run tests using `just test` or `pytest`.**
- **No mocks.** Test against real data or captured responses.
  No `unittest.mock`, `monkeypatch`, stubs, fakes, or simulated environments.

### Banned patterns — the principle

**A provider must never present fabricated data to the user.
Crashing with a visible error is always correct.
Producing plausible-looking output from a broken parser is fraud.**

**Every piece of code must assert that the resource it needs exists, and fail
immediately if it does not.
Fallbacks, defaults, silent recovery, and synthetic data are never acceptable.** If
`fetch_raw` needs a file, the file must be present.
If `to_rows` needs a key, the key must be in the dict.
If an API is required, the endpoint must respond.
The only acceptable failure mode is visible failure.

| Pattern | Why it's an instance of the principle |
| --- | --- |
| `raw.get("key", 0.0)` in `to_rows` | A missing key produces `0.0`, which looks like "0% used — everything is fine." User can't tell the difference between a real zero and a broken parser. |
| `return {}` from `fetch_raw` on parse failure | `{}` flows through `to_rows` and every `.get(key, default)` produces a default. User sees a full table of fabricated data. |
| `pct_used=0.0` as default | A fresh quota window and a broken parser are indistinguishable — both produce 0%. |
| `{"count": 0}` when state file doesn't exist | User sees "0 requests used" and thinks the tool is working. The tool is disconnected. |
| Hand-constructed `UsageRow` in provider tests | Proves the renderer works, proves nothing about the provider. Skips the entire data-collection boundary. |

### What constitutes a provider test

A valid test for provider `Foo` must:

1. Have a captured real response from `foo fetch` / `foo usage` / the relevant API (or a
   minimal fixture that preserves the real boundary structure).
2. Call `FooProvider().fetch_raw()` or simulate the boundary with the captured response
   as input.
3. Call `FooProvider().to_rows(raw)` and assert the resulting `UsageRow` fields match
   expected values — exact `pct_used`, exact `reset_at`, exact `identifier`.
4. Test at least one failure mode: missing credentials, malformed response, timeout, or
   exhausted quota — asserted by `sys.exit` or exception type, not error message string.

### Audit procedure for existing tests

Before keeping any test, classify it:

- **Owned substantive** — Proves repository-owned nontrivial behavior (parsing,
  normalization, failure handling).
- **Boundary/interlock** — Proves correct interaction at an owned edge (CLI output →
  data model).
- **Redundant** — Repeats an already-proved claim without adding a new owned guarantee.
- **Dependency-owned** — Tests rich, pydantic, or another dependency rather than
  repository logic.
- **Private trivia** — Tests internal details with no meaningful contract value.

Keep the first two. Delete the rest.

## Key Files

- `src/usage_limits/base.py`: Abstract base class for providers.
- `src/usage_limits/contracts.py`: Data models and contracts.
- `src/usage_limits/registry.py`: Provider registration and discovery.
- `src/usage_limits/table.py`: Table rendering logic.
- `src/usage_limits/providers/`: Individual service implementations.
