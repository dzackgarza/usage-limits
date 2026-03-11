# AGENTS.md

## Project Overview
`usage-limits` is a Python-based tool and library for tracking and reporting usage quotas for various AI models and services (e.g., Anthropic, OpenAI, OpenRouter, GitHub Copilot). It provides a unified interface for fetching raw usage data, converting it to normalized usage rows, and rendering these as human-readable tables or firing notifications (via `ntfy`) when limits are reached.

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
- New providers should be added to `src/usage_limits/providers/` and registered in `src/usage_limits/registry.py`.

## Testing Requirements
- Unit tests for all providers and core logic in `tests/`.
- Run tests using `just test` or `pytest`.
- **No mocks:** Test against real data or captured responses where possible, but prioritize correctness proofs over coverage metrics.

## Key Files
- `src/usage_limits/base.py`: Abstract base class for providers.
- `src/usage_limits/contracts.py`: Data models and contracts.
- `src/usage_limits/registry.py`: Provider registration and discovery.
- `src/usage_limits/table.py`: Table rendering logic.
- `src/usage_limits/providers/`: Individual service implementations.
