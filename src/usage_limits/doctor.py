"""Diagnostic checks for provider credential readiness.

Each ``doctor()`` run returns a list of provider-level results that
the CLI ``usage-limits doctor`` command renders as a Rich table.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import NamedTuple

_COCKPIT_DIR = Path.home() / ".antigravity_cockpit"


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


def _cockpit_tool() -> str | None:
    """Return the path to cockpit-tools, or None."""
    return shutil.which("cockpit-tools")


def _json_load(path: Path) -> dict | list | None:
    """Safely load a JSON file, returning None on any failure."""
    try:
        data = json.loads(path.read_text())
        if isinstance(data, (dict, list)):
            return data
        return None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _check_cockpit_dir() -> list[Check]:
    """Check the cockpit-tools installation and data directory."""
    checks: list[Check] = []

    cockpit = _cockpit_tool()
    if cockpit:
        checks.append(
            Check(
                description=f"cockpit-tools installed at {cockpit}",
                status="ok",
            )
        )
    else:
        checks.append(
            Check(
                description="cockpit-tools not found in PATH",
                status="error",
                remediation=(
                    "Install from https://github.com/jlcodes99/cockpit-tools\n"
                    "  - Download the latest release for your OS\n"
                    "  - Or build from source: cargo build --release\n"
                    "  - The binary should be placed in your PATH"
                ),
            )
        )
        return checks  # no point checking further

    if _COCKPIT_DIR.is_dir():
        checks.append(
            Check(
                description=f"config directory exists at {_COCKPIT_DIR}",
                status="ok",
            )
        )
    else:
        checks.append(
            Check(
                description="cockpit config directory missing",
                status="error",
                remediation=(
                    "Run cockpit-tools at least once to create the config directory\n"
                    "  - Launch cockpit-tools and complete the Google OAuth login\n"
                    "  - After logging in, accounts appear in ~/.antigravity_cockpit/"
                ),
            )
        )
    return checks


def _check_cockpit_account_index(name: str, label: str) -> list[Check]:
    """Check a service-specific account index under the cockpit dir."""
    checks: list[Check]
    path = _COCKPIT_DIR / f"{name}.json"
    data = _json_load(path)
    if data is None:
        checks = [
            Check(
                description=f"{label} account index missing at {path}",
                status="error",
                remediation=(
                    f"Add a {label} account in the cockpit-tools UI.\n"
                    f"  - Open cockpit-tools → add a {label} account via OAuth\n"
                    f"  - Once added, {path} is created automatically"
                ),
            )
        ]
        return checks

    accounts = data.get("accounts") if isinstance(data, dict) else None
    if not accounts:
        checks = [
            Check(
                description=f"{label} index exists but contains no accounts ({path})",
                status="warning",
                remediation=(f"Add at least one {label} account in cockpit-tools."),
            )
        ]
        return checks

    count = len(accounts)
    emails = []
    for a in accounts:
        if isinstance(a, dict):
            emails.append(a.get("email", a.get("id", "?")))
        else:
            emails.append(str(a))
    checks = [
        Check(
            description=f"{label} account index found: {count} account(s)",
            status="ok",
        ),
        Check(
            description=f"  accounts: {', '.join(emails)}",
            status="ok",
        ),
    ]

    # Check individual account files
    acct_dir = _COCKPIT_DIR / name
    missing_files = 0
    expired_tokens = 0
    for entry in accounts:
        if not isinstance(entry, dict):
            continue
        acct_id = entry.get("id")
        if not acct_id:
            continue
        acct_path = acct_dir / f"{acct_id}.json"
        acct_data = _json_load(acct_path)
        if acct_data is None:
            missing_files += 1
            continue
        # Check for a usable credential
        token = None
        if isinstance(acct_data, dict):
            token = (
                acct_data.get("tokens")
                or acct_data.get("access_token")
                or (acct_data.get("token") or {}).get("access_token")
            )
        if not token:
            expired_tokens += 1

    if missing_files:
        checks.append(
            Check(
                description=f"{missing_files} account file(s) missing in {acct_dir}",
                status="error",
                remediation=(
                    "Re-add the affected accounts in cockpit-tools.\n"
                    "  The missing files indicate credentials were not stored."
                ),
            )
        )
    else:
        checks.append(
            Check(
                description=f"account files present ({acct_dir})",
                status="ok",
            )
        )

    if expired_tokens:
        checks.append(
            Check(
                description=f"{expired_tokens} account(s) have no usable OAuth tokens",
                status="error",
                remediation=(
                    "Re-authenticate the affected accounts in cockpit-tools.\n"
                    "  The tokens may have expired and need refreshing."
                ),
            )
        )
    else:
        checks.append(
            Check(
                description="accounts have OAuth tokens",
                status="ok",
            )
        )

    return checks


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


# ---------------------------------------------------------------------------
# Provider checks
# ---------------------------------------------------------------------------


def doctor() -> list[Result]:
    """Run all diagnostic checks and return per-component results."""
    results: list[Result] = []
    checks: list[Check]

    # ---- cockpit-tools infrastructure ----
    checks = _check_cockpit_dir()
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="cockpit-tools", status=status, checks=checks))

    # Bail early if cockpit-tools is not installed
    if _cockpit_tool() is None:
        return results

    # ---- Antigravity ----
    checks = _check_cockpit_account_index(
        "accounts", "Antigravity"
    )  # file: accounts.json, dir: accounts/
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="antigravity", status=status, checks=checks))

    # ---- Codex (cockpit path) ----
    checks = list(_check_cockpit_account_index("codex_accounts", "Codex"))
    # Also check standalone fallback
    checks.append(
        _check_standalone_file(
            Path.home() / ".codex" / "auth.json",
            "Codex CLI auth (fallback)",
        )
    )
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="codex", status=status, checks=checks))

    # ---- Kiro (cockpit path) ----
    checks = list(_check_cockpit_account_index("kiro_accounts", "Kiro"))
    # Also check standalone SQLite fallback
    kiro_db = Path.home() / ".local" / "share" / "kiro-cli" / "data.sqlite3"
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
                status="warning",
                remediation=(
                    "Install kiro-cli and log in, or add a Kiro account in cockpit-tools.\n"
                    "  The cockpit kiro_accounts files currently lack usable API tokens\n"
                    "  and a full per-account conversion is pending."
                ),
            )
        )
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="kiro", status=status, checks=checks))

    # ---- Claude ----
    checks = [
        _check_standalone_file(
            Path.home() / ".claude" / ".credentials.json",
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
            Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb",
            "Cursor state DB",
        ),
    ]
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="cursor", status=status, checks=checks))

    # ---- Trae ----
    checks = [
        _check_standalone_file(
            Path.home() / ".config" / "Trae" / "User" / "globalStorage" / "storage.json",
            "Trae storage",
        ),
    ]
    status = "ok" if all(c.status == "ok" for c in checks) else "error"
    results.append(Result(component="trae", status=status, checks=checks))

    return results
