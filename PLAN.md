# Multi-Account Provider Support — Implementation Plan

> **TDD.** Red first. Every task: write failing test → run (red) → write code → run
> (green) → commit.

**Goal:** Make accounts a first-class framework concept so providers with multiple
credentials (Antigravity) produce one `ProviderSnapshot` per account instead of jamming
all accounts into one flat row list.

**Design:**

```
UsageProvider (ABC) — unchanged
    └── ProviderAccount(UsageProvider, ABC) — new, adds account_id: str
           ├── ClaudeProvider(ProviderAccount) — single account, account_id="default"
           ├── CopilotProvider(ProviderAccount) — single account
           ├── AntigravityAccount(ProviderAccount) — per-email instances
           └── ...
```

- `ProviderSnapshot` gains an `account: str | None` field
- Registry fans out: one provider slug → (one snapshot per account)
- Collection output is keyed by `(slug, account)` pairs
- Single-account providers reproduce current behavior exactly via default
  `account_id="default"`

* * *

### Task 1: Add `account` field to ProviderSnapshot

**Objective:** Contracts change so every snapshot carries an account identifier.
Default `None` preserves backward compat for external consumers.

**Files:**
- Modify: `src/usage_limits/contracts.py`

**Step 1: Write failing test (test that `account` field exists)**

Read current tests to find best location — add to `tests/test_registry.py` or create
`tests/test_base.py`.

```python
# tests/test_base.py
from usage_limits.contracts import ProviderSnapshot

def test_provider_snapshot_has_account_field() -> None:
    snap = ProviderSnapshot(provider="test", display_name="Test", status="ok")
    assert hasattr(snap, "account")
    assert snap.account is None  # default
```

Run: `pytest tests/test_base.py -v` — expects FAIL (field doesn't exist yet)

**Step 2: Add field to ProviderSnapshot**

```python
class ProviderSnapshot(BaseModel):
    provider: str
    display_name: str
    status: Literal["ok", "error", "rate_limited"]
    rows: list[UsageRow] = Field(default_factory=list)
    availability: list[ModelAvailability] = Field(default_factory=list)
    account: str | None = None                     # ← new field
    metadata: dict[str, Any] = Field(default_factory=dict)
    errors: list[ProviderError] = Field(default_factory=list)
```

**Step 3: Run test to verify pass**

Run: `pytest tests/test_base.py -v` — expects PASS

**Step 4: Verify existing contracts + tree still works**

Run: `just test` — expects green

**Step 5: Commit**

* * *

### Task 2: Define ProviderAccount ABC in base.py

**Objective:** New ABC `ProviderAccount(UsageProvider)` adds `account_id: str`. All
existing providers will eventually inherit from this instead of `UsageProvider`.

**Files:**
- Create test: `tests/test_base.py` (or append if exists)
- Modify: `src/usage_limits/base.py`

**Step 1: Write failing tests**

```python
# tests/test_base.py
import pytest
from usage_limits.base import ProviderAccount, UsageProvider

def test_provider_account_is_subclass_of_usage_provider() -> None:
    assert issubclass(ProviderAccount, UsageProvider)

def test_provider_account_is_abstract() -> None:
    with pytest.raises(TypeError):
        ProviderAccount()  # abstract — has no slug/name etc

class _ConcreteAccount(ProviderAccount):
    slug = "test-acct"
    name = "Test Account"
    state_dir = "test"
    def provider_name(self) -> str: return "Test"
    def fetch_raw(self): return {}
    def to_rows(self, raw): return []
    def should_anchor(self, rows): return False
    def notify_always(self, rows): pass

def test_provider_account_has_account_id() -> None:
    a = _ConcreteAccount()
    assert a.account_id == "default"

def test_provider_account_accepts_custom_account_id() -> None:
    a = _ConcreteAccount(account_id="user@example.com")
    assert a.account_id == "user@example.com"
```

Run: `pytest tests/test_base.py -v` — expects FAIL (no ProviderAccount yet)

**Step 2: Write minimal implementation**

```python
# base.py — after UsageProvider class

class ProviderAccount(UsageProvider, ABC):
    """Provider bound to a specific account.

    Single-account providers use ``account_id="default"``.
    Multi-account providers create one instance per account.
    """

    def __init__(self, account_id: str = "default") -> None:
        super().__init__()
        self.account_id = account_id
```

**Step 3: Run tests — expect PASS**

Run: `pytest tests/test_base.py -v` — expects PASS

**Step 4: Commit**

* * *

### Task 3: Migrate one single-account provider (Claude) to ProviderAccount

**Objective:** Prove backward compat — ClaudeProvider inherits ProviderAccount instead
of UsageProvider, all existing tests pass unchanged.

**Files:**
- Modify: `src/usage_limits/providers/claude.py`
- Run: existing tests in `tests/test_claude*.py`

**Step 1: No new tests needed — existing test suite proves backward compat.**

Change ClaudeProvider:
```python
# Before
class ClaudeProvider(UsageProvider):
    def __init__(self) -> None:
        super().__init__()
        ...

# After  
class ClaudeProvider(ProviderAccount):
    # inherits __init__ with account_id="default"
    ...
```

**Step 2: Run existing Claude tests**

Run: `pytest -k claude -v` — expects PASS

**Step 3: Commit**

* * *

### Task 4: Migrate ALL remaining single-account providers

**Objective:** Every provider that currently extends `UsageProvider` now extends
`ProviderAccount`. One commit per provider, each verified.

**Providers to migrate (all single-account):**
- `ClaudeProvider` — done in Task 3
- `CodexProvider` — `src/usage_limits/providers/codex.py`
- `CopilotProvider` — `src/usage_limits/providers/copilot.py`
- `CursorProvider` — `src/usage_limits/providers/cursor.py`
- `KiroProvider` — `src/usage_limits/providers/kiro.py`
- `OllamaProvider` — `src/usage_limits/providers/ollama.py`
- `OpenCodeGoProvider` — `src/usage_limits/providers/opencode.py`
- `OpenCodeZenProvider` — `src/usage_limits/providers/opencode.py`
- `QoderProvider` — `src/usage_limits/providers/qoder.py`
- `TraeProvider` — `src/usage_limits/providers/trae.py`
- `WindsurfProvider` — `src/usage_limits/providers/windsurf.py`
- `OpenRouterProvider` — `src/usage_limits/providers/openrouter.py`

**For each:**
1. Change `class FooProvider(UsageProvider):` → `class FooProvider(ProviderAccount):`
2. Run `pytest -k foo -v` — expects PASS
3. Commit

* * *

### Task 5: Update collect_provider to emit account-tagged snapshots

**Objective:** `collect_provider` now attaches the account_id to the snapshot it
returns. Single-account providers produce `account="default"`. This is the plumbing
change that makes account info appear in output.

**Files:**
- Modify: `src/usage_limits/registry.py`
- Test: `tests/test_registry.py`

**Step 1: Write failing test**

```python
# tests/test_registry.py
from usage_limits.registry import collect_provider

def test_collect_provider_sets_account() -> None:
    snap = collect_provider("claude")
    assert snap.account is not None
    assert snap.account == "default"
```

Run: `pytest tests/test_registry.py -v` — expects FAIL (account not set)

**Step 2: Modify collect_provider**

```python
def collect_provider(provider: str, *, notify=False, anchor=False) -> ProviderSnapshot:
    provider_class = get_provider_class(provider)
    try:
        instance = provider_class()
        snap = instance.collect_snapshot(notify=notify, anchor=anchor)

        # Tag with account_id if ProviderAccount, else None
        account: str | None = getattr(instance, "account_id", None)

        return ProviderSnapshot(
            provider=snap.provider,
            display_name=snap.display_name,
            status=snap.status,
            rows=snap.rows,
            availability=snap.availability,
            account=account,
            metadata=snap.metadata,
            errors=snap.errors,
        )
    except BaseException as error:
        return _error_snapshot(provider_class, error)
```

Wait — this is awkward because `ProviderSnapshot` is frozen and I'd be constructing a
new one. Better to just set it in `collect_snapshot` directly, or pass `account` through
`collect_snapshot`.

Actually, the cleanest way: `collect_snapshot` in `ProviderAccount` sets the account
field. The base `UsageProvider.collect_snapshot` stays as-is.
Let me think...

Actually, the simplest approach: `collect_provider` just sets the account after getting
the snapshot. But `ProviderSnapshot` is frozen (model_config = ConfigDict(frozen=True)).
So I need to construct a new one or unfreeze it.

Better: pass account through to `collect_snapshot` or have `ProviderAccount` override
`collect_snapshot` to set account.

Actually even simpler: just reconstruct the ProviderSnapshot with the account field set.
Since it's a pydantic model with frozen=True, I can use `model_copy` or reconstruct.

Or: remove `frozen=True` from `ProviderSnapshot`. Let me check if that matters.

Actually, the simplest approach that doesn't break anything: have
`ProviderAccount.collect_snapshot` set the account in the returned snapshot:

```python
class ProviderAccount(UsageProvider, ABC):
    def collect_snapshot(self, **kwargs) -> ProviderSnapshot:
        snap = super().collect_snapshot(**kwargs)
        # Rebuild with account set
        return snap.model_copy(update={"account": self.account_id})
```

But `model_copy` with frozen=True... let me check.
Actually `model_copy(update=...)` works even with frozen=True — frozen prevents direct
field mutation but model_copy creates a new instance.

Let me just write the test, verify it fails, then implement.

**Step 3: Verify test passes after implementation**

Run: `pytest tests/test_registry.py::test_collect_provider_sets_account -v`

**Step 4: Commit**

* * *

### Task 6: Convert Antigravity to per-account instances

**Objective:** Antigravity creates one ProviderAccount per email.
Registry collects them all.

**Files:**
- Modify: `src/usage_limits/providers/antigravity.py`
- Test: `tests/test_antigravity.py`
- Modify: `src/usage_limits/registry.py`

**Step 1: Write test that multiple Antigravity accounts produce multiple snapshots**

```python
# tests/test_antigravity.py
from usage_limits.registry import collect_all

def test_antigravity_produces_per_account_snapshots() -> None:
    collection = collect_all(providers=["antigravity"])
    antigravity_snaps = [s for s in collection.providers if s.provider == "antigravity"]
    assert len(antigravity_snaps) >= 1
    for snap in antigravity_snaps:
        assert snap.account is not None
        assert "@" in snap.account  # email-like
```

Run: `pytest -k antigravity -v` — expects FAIL

**Step 2: Refactor AntigravityProvider into per-account flavor**

AntigravityProvider becomes `AntigravityAccount(ProviderAccount)`:

```python
class AntigravityAccount(ProviderAccount):
    slug = "antigravity"
    name = "Antigravity"
    ...

    def __init__(self, account_id: str, access_token: str) -> None:
        super().__init__(account_id=account_id)
        self._access_token = access_token

    def fetch_raw(self) -> AntigravityRaw:
        # Use self._access_token instead of _get_all_access_tokens
        ...

    def to_rows(self, raw) -> list[UsageRow]:
        ...  # unchanged, but no longer embeds email in identifier
```

Add account resolution to registry:
```python
# registry.py
def _resolve_accounts(provider_class: type[UsageProvider]) -> list[dict]:
    """Return list of account kwargs for a multi-account provider, or [{}] for single."""
    if hasattr(provider_class, "_resolve_accounts"):
        return provider_class._resolve_accounts()
    return [{}]

def collect_provider(provider: str, *, account: str | None = None, ...) -> ProviderSnapshot:
    ...
```

Actually this is getting complicated for the plan.
Let me simplify — the Antigravity refactor is the last and most complex step.
Let me keep the plan scoped to the core Tasks 1-5 first, and treat Antigravity as Task
6\.

* * *

### Task 7: Update rendering to show account

**Objective:** The output table shows account alongside provider name for multi-account
providers.

**Files:**
- Modify: `src/usage_limits/rendering.py` (or wherever display logic lives)

**Step 1: Write test**

Check that rendered output for a multi-account provider includes the account identifier.

**Step 2: Update rendering**

When `snap.account` is set and not "default", display `"{display_name} ({account})"`
instead of just `"{display_name}"`.

* * *

### Summary (uncommitted checkpoints at end)

- Task 1: ProviderSnapshot.account field
- Task 2: ProviderAccount ABC
- Task 3: Migrate one provider (Claude)
- Task 4: Migrate all other single-account providers
- Task 5: Registry plumbs account into snapshots
- Task 6: Antigravity per-account instances
- Task 7: Rendering shows account
