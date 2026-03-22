set fallback := true
repo_root := justfile_directory()
python_qc_justfile := env_var_or_default("OPENCODE_PYTHON_QC_JUSTFILE", "/home/dzack/ai/quality-control/justfile")

default:
    @just test

install:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{repo_root}}"
    exec uv sync --all-groups

serve:
    uv run otlp-collector --port 4318

[private]
_format:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{repo_root}}"
    exec direnv exec "{{repo_root}}" uv run ruff format .

[private]
_lint:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{repo_root}}"
    exec direnv exec "{{repo_root}}" uv run ruff check .

[private]
_typecheck:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{repo_root}}"
    exec direnv exec "{{repo_root}}" uv run mypy -p usage_limits

[private]
_quality-control:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{repo_root}}"
    if git remote get-url origin >/dev/null 2>&1; then
        if [[ "$(git rev-parse --is-shallow-repository)" == "true" ]]; then
            git fetch --no-tags --prune --unshallow origin || true
        else
            git fetch --no-tags --prune origin || true
        fi
        git fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main || true
        export DIFF_COVER_BASE="origin/main"
    fi
    direnv exec "{{repo_root}}" just --justfile "{{python_qc_justfile}}" --working-directory "{{repo_root}}" _diff-cover
    direnv exec "{{repo_root}}" just --justfile "{{python_qc_justfile}}" --working-directory "{{repo_root}}" _vulture
    exec direnv exec "{{repo_root}}" just --justfile "{{python_qc_justfile}}" --working-directory "{{repo_root}}" _deptry

test: _lint _typecheck _quality-control

check: test

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

_install-service:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "$HOME/.config/systemd/user" "$HOME/.config/usage-limits"
    token_file="{{repo_root}}/.env"
    envrc_file="{{repo_root}}/.envrc"
    if grep -q '^OPENROUTER_SINK_TOKEN=' "$token_file" 2>/dev/null; then
        grep '^OPENROUTER_SINK_TOKEN=' "$token_file" > "$HOME/.config/usage-limits/sink.env"
    elif grep -q '^export OPENROUTER_SINK_TOKEN=' "$envrc_file" 2>/dev/null; then
        grep '^export OPENROUTER_SINK_TOKEN=' "$envrc_file" | sed 's/^export //' > "$HOME/.config/usage-limits/sink.env"
    else
        echo "ERROR: OPENROUTER_SINK_TOKEN not found in .env or .envrc" >&2
        exit 1
    fi
    cp "{{repo_root}}/usage-limits-sink.service" "$HOME/.config/systemd/user/usage-limits-sink.service"
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
