set fallback := true
# justfile for usage-limits
#
# WORKFLOW: Always run `just test`. Do NOT add public recipes for
# additional checks. The `test` recipe depends on the full quality
# control stack — bypassing it defeats the purpose of enforced gates.
# Add new analyses as private recipes (prefix with _) and add them to
# the `test` dependency list.

default:
    @just test

# private recipes (prefix with _ — do not run individually in CI)
_venv:
    #!/usr/bin/env bash
    set -euo pipefail
    # Create venv if it doesn't exist, otherwise skip
    if [ ! -d ".venv" ]; then
        uv venv
    fi

_install: _venv
    #!/usr/bin/env bash
    set -euo pipefail
    uv sync --all-groups

_lint: _install
    #!/usr/bin/env bash
    set -euo pipefail
    uv run ruff check .

_typecheck: _install
    #!/usr/bin/env bash
    set -euo pipefail
    uv run mypy -p usage_limits

_test: _install
    #!/usr/bin/env bash
    set -euo pipefail
    uv run pytest

# Canonical CLI surfaces (private — use for manual testing)
_collect *ARGS:
    uv run usage-limits --json {{ARGS}}

_table *ARGS:
    uv run usage-limits {{ARGS}}

_providers *ARGS:
    uv run usage-limits providers list {{ARGS}}

_claude *ARGS:
    uv run usage-claude {{ARGS}}

_codex *ARGS:
    uv run usage-codex {{ARGS}}

_amp *ARGS:
    uv run usage-amp {{ARGS}}

_antigravity *ARGS:
    uv run usage-antigravity {{ARGS}}

_openrouter *ARGS:
    uv run usage-openrouter {{ARGS}}

_qwen *ARGS:
    uv run usage-qwen {{ARGS}}

_ollama *ARGS:
    uv run usage-ollama {{ARGS}}

_copilot *ARGS:
    uv run usage-copilot {{ARGS}}

_gemini *ARGS:
    uv run usage-gemini {{ARGS}}

# Version management (private)
_v:
    @uv version | awk '{print $2}'

_bump-patch: _test
    uv version --bump patch
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

_bump-minor: _test
    uv version --bump minor
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

_bump-major: _test
    uv version --bump major
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

_publish:
    git push origin $(git branch --show-current) --tags

# OTLP sink (private — for development only)
_serve:
    uv run otlp-collector --port 4318

_install-service:
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

_uninstall-service:
    #!/usr/bin/env bash
    set -euo pipefail
    systemctl --user stop usage-limits-sink || true
    systemctl --user disable usage-limits-sink || true
    rm -f "$HOME/.config/systemd/user/usage-limits-sink.service"
    systemctl --user daemon-reload

# top-level test depends on all quality gates
test: _lint _typecheck _test
    #!/usr/bin/env bash
    set -euo pipefail
    echo "All analyses completed"
