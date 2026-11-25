[doc("Default: show available commands")]
default:
    @just --list

qc-type := "python"

ai_review_ci_schema_version := "1"
ai_review_ci_profile := "python"
ai_review_ci_ref := "main"
ai_review_ci_release_channel := "main"
ai_review_ci_workflow_template_version := "1"
ai_review_ci_local_delegation := "global-justfile"
ai_review_ci_default_branch := "main"

[doc("Set up the project (uv venv + install)")]
setup:
    uv venv
    uv sync --all-groups

[doc("Run the full check suite")]
check: lint typecheck test

[doc("Run the full CI check suite (delegated to ai-review-ci)")]
test-ci:
    @just -f ~/ai-review-ci/justfiles/python.just -d . test-ci

[doc("Run the commit-tier QC gate (delegated to ai-review-ci)")]
test-commit:
    @just -f ~/ai-review-ci/justfiles/python.just -d . test-commit

[doc("Run the push-tier QC gate (delegated to ai-review-ci)")]
test-push:
    @just -f ~/ai-review-ci/justfiles/python.just -d . test-push

[doc("Format and auto-fix")]
fmt:
    uv run ruff format .
    uv run ruff check --fix .

[doc("Lint only")]
lint:
    uv run ruff check .

[doc("Type check")]
typecheck:
    uv run mypy -p usage_limits

[doc("Run tests")]
test *ARGS:
    uv run pytest {{ARGS}}

[doc("Print usage limits as JSON")]
collect *ARGS:
    uv run usage-limits --json {{ARGS}}

[doc("Print usage limits as a table")]
table *ARGS:
    uv run usage-limits {{ARGS}}

[doc("List the configured providers")]
providers *ARGS:
    uv run usage-limits providers list {{ARGS}}

[doc("Run the Claude usage checker")]
claude *ARGS:
    uv run usage-claude {{ARGS}}

[doc("Run the Codex usage checker")]
codex *ARGS:
    uv run usage-codex {{ARGS}}

[doc("Run the Antigravity usage checker")]
antigravity *ARGS:
    uv run usage-antigravity {{ARGS}}

[doc("Run the OpenRouter usage checker")]
openrouter *ARGS:
    uv run usage-openrouter {{ARGS}}

[doc("Run the Ollama usage checker")]
ollama *ARGS:
    uv run usage-ollama {{ARGS}}

[doc("Get the current version number")]
v:
    @uv version | awk '{print $2}'

[doc("Release current state as a patch (default)")]
release: release-patch

[doc("Release a patch version")]
release-patch: bump-patch publish
    @gh release create v$(uv version | awk '{print $2}') --generate-notes

[doc("Release a minor version")]
release-minor: bump-minor publish
    @gh release create v$(uv version | awk '{print $2}') --generate-notes

[doc("Release a major version")]
release-major: bump-major publish
    @gh release create v$(uv version | awk '{print $2}') --generate-notes

[doc("Default: bump patch, commit, and tag")]
bump: bump-patch

[doc("Bump patch, commit, and tag")]
bump-patch: check
    uv version --bump patch
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

[doc("Bump minor, commit, and tag")]
bump-minor: check
    uv version --bump minor
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

[doc("Bump major, commit, and tag")]
bump-major: check
    uv version --bump major
    git add pyproject.toml
    git commit -m "chore: bump version to v$(uv version | awk '{print $2}')"
    git tag v$(uv version | awk '{print $2}')

[doc("Publish: push current branch and tags to trigger GitHub Action")]
publish:
    git push origin $(git branch --show-current) --tags

[doc("Install default config file (does not overwrite existing)")]
init-config:
    mkdir -p ~/.config/usage-limits
    test -f ~/.config/usage-limits/config.toml || cp .config/usage-limits/config.toml ~/.config/usage-limits/config.toml

[doc("Build the source and wheel distributions")]
build:
    uv build
