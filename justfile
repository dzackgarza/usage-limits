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

# Get the current version number
v:
    @uv version | awk '{print $2}'

# Default: bump patch, commit, and tag
bump: bump-patch

# Bump patch, commit, and tag
bump-patch: check
    uv version --bump patch
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

# Bump minor, commit, and tag
bump-minor: check
    uv version --bump minor
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

# Bump major, commit, and tag
bump-major: check
    uv version --bump major
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

# Publish: push current branch and tags to trigger GitHub Action
publish:
    git push origin $(git branch --show-current) --tags

build:
    uv build
