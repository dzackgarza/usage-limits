# Default: show available commands
default:
    @just --list

qc-type := "python"

# ai-review-ci contract variables consumed by doctor and workflow installers.
ai_review_ci_schema_version := "1"
ai_review_ci_profile := "python"
ai_review_ci_ref := "main"
ai_review_ci_release_channel := "main"
ai_review_ci_workflow_template_version := "1"
ai_review_ci_local_delegation := "global-justfile"
ai_review_ci_default_branch := "main"

# Set up the project (uv venv + install)
setup:
    uv venv
    uv sync --all-groups

# Run the full check suite
check: lint typecheck test

# Run the full CI check suite (delegated to ai-review-ci)
test-ci:
    @just -f ~/ai-review-ci/justfiles/python.just -d . test-ci

# Run the commit-tier QC gate (delegated to ai-review-ci)
test-commit:
    @just -f ~/ai-review-ci/justfiles/python.just -d . test-commit

# Run the push-tier QC gate (delegated to ai-review-ci)
test-push:
    @just -f ~/ai-review-ci/justfiles/python.just -d . test-push

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
collect *ARGS:
    uv run usage-limits --json {{ARGS}}

table *ARGS:
    uv run usage-limits {{ARGS}}

providers *ARGS:
    uv run usage-limits providers list {{ARGS}}

# Run a specific provider checker
claude *ARGS:
    uv run usage-claude {{ARGS}}

codex *ARGS:
    uv run usage-codex {{ARGS}}

antigravity *ARGS:
    uv run usage-antigravity {{ARGS}}

openrouter *ARGS:
    uv run usage-openrouter {{ARGS}}

ollama *ARGS:
    uv run usage-ollama {{ARGS}}

# Get the current version number
v:
    @uv version | awk '{print $2}'

# Release current state as a patch (default)
release: release-patch

# Release a patch version
release-patch: bump-patch publish
    @gh release create v$(uv version | awk '{print $2}') --generate-notes

# Release a minor version
release-minor: bump-minor publish
    @gh release create v$(uv version | awk '{print $2}') --generate-notes

# Release a major version
release-major: bump-major publish
    @gh release create v$(uv version | awk '{print $2}') --generate-notes

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

# Install default config file (does not overwrite existing)
init-config:
    mkdir -p ~/.config/usage-limits
    test -f ~/.config/usage-limits/config.toml || cp .config/usage-limits/config.toml ~/.config/usage-limits/config.toml

build:
    uv build
