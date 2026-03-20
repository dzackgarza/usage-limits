# Problem

usage-limits has multiple issues:

1. Embedded OTLP HTTP sink (`server.py`) duplicates functionality of standalone `otlp-collector` package
2. Provider implementations don't align with OpenChamber's canonical implementation
3. Missing providers (GitHub Copilot, proper OpenRouter tracking)
4. Gemini CLI missing models (only shows used models, not all available)
5. No automatic OAuth token refresh for expired credentials
6. Documentation violates guidelines (decision logs, work summaries in docs/)

# Intended outcome

After this PR lands:

- usage-limits reads from centralized `otlp-collector` SQLite database
- All providers aligned with OpenChamber's implementation (same auth sources, API endpoints, data parsing)
- 9 providers working: Amp, Antigravity, Claude, Codex, GitHub Copilot, Gemini CLI, Ollama, OpenRouter, Qwen
- Automatic OAuth token refresh for Gemini CLI and Claude
- Gemini CLI shows ALL available models, not just used ones
- OpenRouter counts OTLP spans (not hardcoded to 0)
- Documentation guideline violations removed

# Non-goals

- No changes to OTLP collector itself (separate package)
- No changes to auth file format (uses existing `~/.local/share/opencode/auth.json`)
- No breaking changes to CLI interface or JSON output contract
- No new external dependencies beyond `otlp-collector`

# Constraints

- Must pass all existing tests (50+ tests)
- Must remain mypy strict clean
- Must remain ruff lint clean
- No hardcoded user secrets (OAuth app credentials are public, user tokens are not)
- OpenRouter must count actual usage (not hardcoded to 0)
- Gemini must show all available models (not just used ones)

# Acceptance criteria

- [ ] 50 tests pass (`just test`)
- [ ] ruff lint clean (`just lint`)
- [ ] mypy strict clean (`just typecheck`)
- [ ] `usage-limits -p gemini` shows 7+ models (was showing 4)
- [ ] `usage-limits -p openrouter` shows actual span count (not 0)
- [ ] `usage-limits -p claude` auto-refreshes on 401 error
- [ ] `usage-limits -p copilot` shows 3 quota windows (chat, completions, premium)
- [ ] All providers read from `~/.local/share/opencode/auth.json`
- [ ] No docs/ directory (guideline violations removed)
- [ ] README.md accurately reflects all 9 providers

# Evidence plan

- failing test: N/A (refactoring existing functionality)
- passing tests: `just test` output showing 50 tests pass
- type checking: `just typecheck` output (mypy clean)
- linting: `just lint` output (ruff clean)
- manual verification: `usage-limits` output for all 9 providers
- git diff: `docs/` directory removed (guideline violations)

# Change boundary

Expected touched files/subsystems:

- `src/usage_limits/providers/*.py` - Provider implementations
- `src/usage_limits/registry.py` - Provider registration
- `README.md` - Documentation updates
- `docs/` - Remove guideline-violating files
- `tests/test_*.py` - Test updates for new providers
- `pyproject.toml` - Add otlp-collector dependency

NOT expected to change:

- CLI interface (`src/usage_limits/cli.py`)
- JSON output contract (`src/usage_limits/contracts.py`)
- Base provider class (`src/usage_limits/base.py`)

# Open questions

None - implementation complete.

# Review focus

Please check specifically:

- Whether OAuth credentials in code are application-level (public) not user secrets
- Whether OpenRouter span counting is correct (queries spans table, not logs)
- Whether Gemini model fetching calls both endpoints (quota + available models)
- Whether documentation removal is complete (no decision logs remain)
- Whether all 9 providers work with real credentials
- Whether auto-refresh mechanisms don't introduce infinite loops

# Test plan

```bash
# Run full test suite
just test

# Verify type checking
just typecheck

# Verify linting
just lint

# Manual verification
usage-limits
usage-limits -p gemini
usage-limits -p openrouter
usage-limits -p copilot
```
