# usage-limits

`usage_limits` is the extraction seed for a standalone quota-tracking repo. It exposes one canonical CLI, one normalized JSON contract, and provider submodules that can be extended without turning the package back into a pile of standalone scripts.

## Canonical CLI

Inside this repo:

```bash
cd /home/dzack/ai/scripts/usage_limits
uv run usage-limits providers list
uv run usage-limits collect --provider claude --json
uv run usage-limits availability --all --json
uv run usage-limits table --provider claude --provider codex
```

The public command tree is:

- `usage-limits providers list`
- `usage-limits collect`
- `usage-limits availability`
- `usage-limits table`

Provider aliases such as `usage-claude` and `usage-antigravity` are secondary wrappers around the same normalized implementation.

## JSON Contract

`collect` returns a top-level payload with:

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
uv run usage-limits table --provider claude --notify --anchor
uv run usage-limits collect --provider codex --json --notify --anchor
```

That keeps `uvx` and JSON-consuming callers free of surprising side effects while preserving the operational behaviors when they are actually wanted.

## Provider Coverage

First-party providers currently include:

- `amp`
- `antigravity`
- `claude`
- `codex`
- `ollama`
- `openrouter`
- `qwen`

`openrouter` still returns a normalized error snapshot because request counting is not yet implemented.
