# Suggested commands

## Development

- `just setup` — create venv + install deps
- `just fmt` — ruff format + check --fix
- `just lint` — ruff check
- `just typecheck` — mypy strict on usage_limits
- `just test` — pytest (add `-v`, `-k pattern`, `--tb=long` as needed)
- `just check` — lint + typecheck + test
- `just build` — `uv build`

## CLI usage

- `just collect` — `usage-limits --json` (all providers, JSON output)
- `just table` — `usage-limits` (all providers, rich table output)
- `just providers` — list registered providers
- `just claude` — run Claude Code checker
- `just codex` — run Codex checker
- `just antigravity` — run Antigravity checker
- `just kiro` — run Kiro checker
- `just openrouter` — run OpenRouter checker
- `just ollama` — run Ollama checker

## Release

- `just release` — bump patch + commit + tag + push
- `just release-minor` — bump minor + release
- `just release-major` — bump major + release

## Version

- `just v` — print current version
