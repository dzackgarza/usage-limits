# Default: show available commands
default:
    @just --list

# Set up the project (uv venv + install)
setup:
    uv venv
    uv sync --all-groups

# Run the full check suite
check: lint typecheck test

# Format and auto-fix
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Lint only
lint:
    uv run ruff check .

# Type check
typecheck:
    uv run mypy -p usage_limits

# Run tests
test *ARGS:
    uv run pytest {{ARGS}}

# Install in editable mode in the opencode venv (for use from shell)
install-dev:
    ~/ai/opencode/.venv/bin/pip install -e .

# Canonical CLI surfaces
providers *ARGS:
    uv run usage-limits providers list {{ARGS}}

collect *ARGS:
    uv run usage-limits collect {{ARGS}}

availability *ARGS:
    uv run usage-limits availability {{ARGS}}

table *ARGS:
    uv run usage-limits table {{ARGS}}

# Run a specific provider checker
claude *ARGS:
    uv run usage-claude {{ARGS}}

codex *ARGS:
    uv run usage-codex {{ARGS}}

amp *ARGS:
    uv run usage-amp {{ARGS}}

antigravity *ARGS:
    uv run usage-antigravity {{ARGS}}

openrouter *ARGS:
    uv run usage-openrouter {{ARGS}}

qwen *ARGS:
    uv run usage-qwen {{ARGS}}

ollama *ARGS:
    uv run usage-ollama {{ARGS}}
