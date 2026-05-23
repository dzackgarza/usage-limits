# Task completion

After completing any coding task, run the full check suite:

```
just check
```

This runs: lint → typecheck → test.

## Individual commands

| Step | Command |
|------|---------|
| Format + fix | `just fmt` |
| Lint | `just lint` |
| Type check | `just typecheck` |
| Run tests | `just test` (or `just test -v` for verbose, `just test -k <pattern>` to filter) |
| Full check | `just check` |

If adding a new provider, make sure it's listed in `mem:core` provider table and
the provider appears in `pyproject.toml` `[project.scripts]`, `registry.py`,
and `providers/__init__.py` before committing.
