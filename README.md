[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/I2I57UKJ8)

# usage-limits

Uniform quota collection for CLI- and API-backed LLM providers.

## Setup

```bash
direnv allow
just setup
```

Local configuration lives in `.envrc` and inherits shared shell configuration from
`~/.envrc`:

```bash
source_up

# Required only for the Ollama provider.
# OLLAMA_SESSION_COOKIE=
```

## Direct Use

```bash
uvx --from git+https://github.com/dzackgarza/usage-limits.git \
  usage-limits providers list

uvx --from git+https://github.com/dzackgarza/usage-limits.git \
  usage-limits collect --provider claude --json

uvx --from git+https://github.com/dzackgarza/usage-limits.git \
  usage-limits availability --all --json

uvx --from git+https://github.com/dzackgarza/usage-limits.git \
  usage-limits table --provider claude --provider codex
```

## Commands

- `usage-limits providers list` reports registered provider metadata.
- `usage-limits collect` emits the canonical usage JSON contract.
- `usage-limits availability` emits the availability-only JSON contract.
- `usage-limits table` renders the same data with Rich.
- Provider aliases such as `usage-claude` and `usage-antigravity` are thin wrappers.

## JSON Contract

`collect` returns:

- `version`
- `captured_at`
- `providers`

Each provider entry contains:

- `provider`
- `display_name`
- `status`
- `rows`
- `availability`
- `metadata`
- `errors`

`availability` returns the same top-level framing with provider availability entries only.

## Side Effects

Collection is read-only by default. Notifications and anchoring are explicit:

```bash
usage-limits table --provider claude --notify --anchor
usage-limits collect --provider codex --json --notify --anchor
```

## Provider Coverage

First-party providers currently include:

- `amp`
- `antigravity`
- `claude`
- `codex`
- `ollama`
- `openrouter`
- `qwen`

`openrouter` currently returns a normalized error snapshot because request counting is not
implemented.

## Development

- `just setup` installs the project and dev dependencies.
- `just check` runs lint, tests, and typecheck.
- `just build` builds a wheel and sdist.
- `just bump` increments the minor version with `uv version --bump minor`.
