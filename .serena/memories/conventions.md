# Code conventions

## Typing

- Type hints required on all function signatures and class members.
- TypedDict for every data shape crossing a boundary (API, file, subprocess).
- `dict[str, Any]` banned for structured data.
- `# type: ignore` banned — fix the type definition instead.
- Use `cast()` at JSON decode boundaries (json.loads, resp.json()) as explicit assertion.
- `assert x is not None` acceptable on nullable types.

## Error handling

- No try/except blocks (exception: re-raising non-target status codes in control flow).
- No `print("Error: ...")` + `sys.exit(1)` — let exceptions propagate raw.
- No existence checks before access — let FileNotFoundError/KeyError propagate.
- No `.get(key, default)` with defaults indistinguishable from real values.
- No retry/recovery logic (no re-auth on 401, no retry on timeout).
- Single acceptable failure mode: uncaught exception with traceback.

## Provider contracts

- Inherit `UsageProvider` from `base.py`.
- Must define: `slug`, `name`, `state_dir` class attributes.
- Must implement: `fetch_raw()`, `to_rows(raw)`, `provider_name()`, `should_anchor()`, `notify_always()`.
- Register in `registry.py` `FIRST_PARTY_PROVIDER_CLASSES` and import in `__init__.py`.

## Testing

- Every provider must have a test exercising `fetch_raw` + `to_rows`.
- No mocks, stubs, monkeypatch, or simulated environments — only captured real responses.
- Test at least one failure mode (missing creds, malformed response, timeout, exhausted quota).
- Assert by exception type, not error message string.
- Fixtures go in `tests/fixtures/`.
