set fallback := true
# justfile for usage-limits
#
# PUBLIC INTERFACE (narrow - what users should run):
#   just test       - Run full quality gate suite
#   just install    - Set up development environment
#   just serve      - Start OTLP collector for OpenRouter/Qwen tracking
#
# All other recipes are private implementation details.

default:
    @just --list

# === PUBLIC RECIPES (intended interface) ===

install:
    uv sync --all-groups

test:
    @echo "Running quality gates..."
    @echo "=== Lint ==="
    uv run ruff check .
    @echo "=== Type check ==="
    uv run mypy -p usage_limits
    @echo "=== Tests ==="
    uv run pytest
    @echo "All checks passed!"

serve:
    uv run otlp-collector --port 4318

# === PRIVATE RECIPES (implementation details) ===

_venv:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -d ".venv" ]; then
        uv venv --python 3.11
    fi

_install-tools: _venv
    #!/usr/bin/env bash
    set -euo pipefail
    uv pip install coverage diff-cover vulture deptry semgrep lizard import-linter

# Quality gates (required from ~/ai/quality-control)
_coverage: _install-tools
    uv run coverage run -m pytest
    uv run coverage xml -o coverage.xml

_diff-cover: _coverage
    uv run diff-cover coverage.xml --compare-branch ${DIFF_COVER_BASE:-main}

_vulture: _install-tools
    uv run vulture src tests --min-confidence 60

_deptry: _install-tools
    uv run deptry check src

_semgrep: _install-tools
    uv run semgrep --config=p/ci --inline-suppression

_jscpd:
    npx -y jscpd --path src --reporters console

_lizard: _install-tools
    uv run lizard src -l python -C 7 -L 100 -a 5 -i 0 \
        -x "*/node_modules/*" \
        -x "*/__pycache__/*" \
        -x "*/.venv/*" \
        -x "*/dist/*" \
        -x "*/build/*"

_import-linter: _install-tools
    uv run import-linter check

_codeql:
    codeql database create codeql-db --language=python --source-root=.
    codeql database analyze codeql-db --format=sarif-latest --output=codeql-report.sarif

# Version management (internal)
_bump-patch: test
    uv version --bump patch
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

_bump-minor: test
    uv version --bump minor
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

_bump-major: test
    uv version --bump major
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

# Service management (internal)
_install-service:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "$HOME/.config/systemd/user" "$HOME/.config/usage-limits"
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
