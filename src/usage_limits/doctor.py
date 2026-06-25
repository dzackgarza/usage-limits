"""Diagnostic checks for provider credential readiness.

Each ``doctor()`` run returns a list of provider-level results that
the CLI ``usage-limits doctor`` command renders as a Rich table.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from usage_limits.auth.store import CredentialStore
from usage_limits.config import resolve_path, settings


class Check(NamedTuple):
    """A single diagnostic check."""

    description: str
    status: str  # "ok" | "warning" | "error"
    remediation: str | None = None


class Result(NamedTuple):
    """Aggregated diagnostics for one provider or subsystem."""

    component: str
    status: str  # "ok" | "warning" | "error"
    checks: list[Check]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_standalone_file(
    path: Path,
    label: str,
) -> Check:
    """Check a single credential file exists and is non-empty."""
    try:
        st = path.stat()
        if st.st_size > 0:
            return Check(
                description=f"{label}: {path}",
                status="ok",
            )
        return Check(
            description=f"{label}: {path} is empty",
            status="error",
            remediation=f"Re-authenticate: the file at {path} should contain credentials.",
        )
    except FileNotFoundError:
        return Check(
            description=f"{label}: {path} not found",
            status="error",
            remediation=f"Log in via the relevant CLI to generate {path}.",
        )


def _check_store_provider(store: CredentialStore, provider: str) -> list[Check]:
    accounts = store.list_accounts(provider)
    if not accounts:
        return [
            Check(
                description=f"No {provider} accounts found in store",
                status="error",
                remediation=f"Run `usage-limits login {provider}` to authenticate.",
            )
        ]

    checks = [
        Check(
            description=f"Found {len(accounts)} {provider} account(s): {', '.join(accounts)}",
            status="ok",
        )
    ]

    expired = 0
    for account_id in accounts:
        try:
            cred = store.get(provider, account_id)
            expires_at = cred["expires_at"]
            if expires_at is not None:
                exp = datetime.fromisoformat(expires_at)
                if exp < datetime.now(UTC):
                    expired += 1
        except Exception:
            pass

    if expired > 0:
        checks.append(
            Check(
                description=f"{expired} account(s) have expired tokens",
                status="warning",
                remediation="Tokens will be auto-refreshed on next use.",
            )
        )
    else:
        checks.append(
            Check(
                description="Tokens appear valid",
                status="ok",
            )
        )

    return checks


# ---------------------------------------------------------------------------
# Provider checks
# ---------------------------------------------------------------------------


def doctor() -> list[Result]:
    """Run all diagnostic checks and return per-component results."""
    results: list[Result] = []

    store = CredentialStore(resolve_path(settings.paths.credentials_dir))

    # ---- Credential Store (Global) ----
    if store.root_dir.is_dir():
        checks = [Check(description=f"Credential store exists at {store.root_dir}", status="ok")]
        status = "ok"
    else:
        checks = [
            Check(
                description=f"Credential store missing at {store.root_dir}",
                status="warning",
                remediation="Log in to any provider to create the store.",
            )
        ]
        status = "warning"
    results.append(Result(component="store", status=status, checks=checks))

    # ---- Antigravity ----
    checks = _check_store_provider(store, "antigravity")
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="antigravity", status=status, checks=checks))

    # ---- Codex ----
    checks = _check_store_provider(store, "codex")
    checks.append(
        _check_standalone_file(
            resolve_path(settings.paths.codex_auth),
            "Codex CLI auth (fallback)",
        )
    )
    status = "ok" if any(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="codex", status=status, checks=checks))

    # ---- Kiro ----
    checks = []
    kiro_db = resolve_path(settings.paths.kiro_db)
    try:
        conn = sqlite3.connect(kiro_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM auth_kv WHERE key = 'kirocli:social:token'")
        count = cursor.fetchone()[0]
        conn.close()
        checks.append(
            Check(
                description=f"Kiro CLI SQLite DB: {kiro_db} ({count} token(s))",
                status="ok",
            )
        )
    except (sqlite3.Error, FileNotFoundError):
        checks.append(
            Check(
                description=f"Kiro CLI SQLite DB: {kiro_db} not found or corrupt",
                status="error",
                remediation="Install kiro-cli and log in.",
            )
        )
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="kiro", status=status, checks=checks))

    # ---- Claude ----
    checks = [
        _check_standalone_file(
            resolve_path(settings.paths.claude_credentials),
            "Claude credentials",
        ),
    ]
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="claude", status=status, checks=checks))

    # ---- Copilot ----
    gh_which = shutil.which("gh")
    if gh_which:
        checks = [
            Check(
                description=f"gh CLI installed at {gh_which}",
                status="ok",
            ),
        ]
        import subprocess

        try:
            subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            checks.append(
                Check(
                    description="gh auth: logged in",
                    status="ok",
                )
            )
        except (subprocess.CalledProcessError, OSError):
            checks.append(
                Check(
                    description="gh auth: not logged in or token expired",
                    status="error",
                    remediation=(
                        "Run: gh auth login\n"
                        "  This will prompt you to authenticate with GitHub.\n"
                        "  Copilot usage data requires an active GitHub session."
                    ),
                )
            )
    else:
        checks = [
            Check(
                description="gh CLI not found in PATH",
                status="error",
                remediation=(
                    "Install GitHub CLI: https://cli.github.com/\n"
                    "  Then authenticate: gh auth login"
                ),
            ),
        ]
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="copilot", status=status, checks=checks))

    # ---- Cursor ----
    checks = [
        _check_standalone_file(
            resolve_path(settings.paths.cursor_state_db),
            "Cursor state DB",
        ),
    ]
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="cursor", status=status, checks=checks))

    # ---- Trae ----
    checks = [
        _check_standalone_file(
            resolve_path(settings.paths.trae_storage),
            "Trae storage",
        ),
    ]
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="trae", status=status, checks=checks))

    return results
