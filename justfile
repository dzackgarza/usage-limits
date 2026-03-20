set fallback := true
# Default: show available commands
default:
    @just --list

# Set up the project (uv venv + install)
install:
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

build:
    uv build

# Start the OTLP sink server (foreground, for dev/test)
serve:
    uv run otlp-collector --port 4318

# Install and start the OTLP sink as a persistent systemd user service
install-service:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "$HOME/.config/systemd/user" "$HOME/.config/usage-limits"
    # Resolve the token: prefer .env (local secrets), fall back to .envrc export lines
    token_file="{{justfile_directory()}}/.env"
    envrc_file="{{justfile_directory()}}/.envrc"
    if grep -q '^OPENROUTER_SINK_TOKEN=' "$token_file" 2>/dev/null; then
        grep '^OPENROUTER_SINK_TOKEN=' "$token_file" > "$HOME/.config/usage-limits/sink.env"
    elif grep -q '^export OPENROUTER_SINK_TOKEN=' "$envrc_file" 2>/dev/null; then
        grep '^export OPENROUTER_SINK_TOKEN=' "$envrc_file" | sed 's/^export //' > "$HOME/.config/usage-limits/sink.env"
    else
        echo "ERROR: OPENROUTER_SINK_TOKEN not found in .env or .envrc" >&2
        exit 1
    fi
    cp "{{justfile_directory()}}/usage-limits-sink.service" "$HOME/.config/systemd/user/usage-limits-sink.service"
    systemctl --user daemon-reload
    systemctl --user enable usage-limits-sink
    systemctl --user start usage-limits-sink
    systemctl --user status usage-limits-sink

# Remove the systemd user service
uninstall-service:
    #!/usr/bin/env bash
    set -euo pipefail
    systemctl --user stop usage-limits-sink || true
    systemctl --user disable usage-limits-sink || true
    rm -f "$HOME/.config/systemd/user/usage-limits-sink.service"
    systemctl --user daemon-reload
