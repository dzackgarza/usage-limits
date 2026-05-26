"""Codex usage limits provider.

Depends on cockpit-tools for multi-account credential storage.
Reads the following files from ``~/.antigravity_cockpit/``:

========================= ===========================================
File                      Role
========================= ===========================================
``codex_accounts.json``   V2 account index — lists every known Codex
                          account with an ID, email, and plan type.
                         ``resolve_accounts()`` reads this to
                          discover which accounts exist.
``codex_accounts/<id>.json``  Per-account credential file. Contains
                          the OAuth ``tokens`` dict (with
                          ``access_token``) and cached quota data.
                         ``get_credentials()`` reads this to obtain
                          the access token for each account.
========================= ===========================================

When constructed directly (``account_id="default"``), falls back to
``~/.codex/auth.json`` for backward compatibility with the standard
Codex CLI auth file.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.table import UsageRow

COCKPIT_DIR = Path.home() / ".antigravity_cockpit"
CODEX_ACCOUNTS_INDEX_PATH = COCKPIT_DIR / "codex_accounts.json"
CODEX_ACCOUNTS_DIR = COCKPIT_DIR / "codex_accounts"


class CodexTokens(TypedDict):
    access_token: str
    refresh_token: str
    id_token: str
    account_id: str


class CodexCredentials(TypedDict):
    access_token: str


class CodexAccountEntry(TypedDict):
    id: str
    email: str
    plan_type: str
    subscription_active_until: str
    created_at: int
    last_used: int


class CodexAccountIndex(TypedDict):
    version: str
    accounts: list[CodexAccountEntry]
    current_account_id: str | None


class CodexAccountFile(TypedDict):
    id: str
    email: str
    tokens: CodexTokens
    quota: dict


class WhamWindow(TypedDict):
    used_percent: float
    reset_at: int | None


class WhamRateLimit(TypedDict):
    primary_window: WhamWindow
    secondary_window: WhamWindow | None


class WhamUsageResponse(TypedDict):
    rate_limit: WhamRateLimit


class CodexProvider(ProviderAccount):
    """Codex CLI usage checker (5-hour and 7-day WHAM windows).

    One instance per credential email. Use ``resolve_accounts()`` to
    discover all accounts from the cockpit-tools codex accounts file
    layout (``codex_accounts.json`` + ``codex_accounts/<id>.json``).
    """

    slug = "codex"
    name = "Codex"
    state_dir = "codex_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self, account_id: str = "default") -> None:
        super().__init__(account_id=account_id)

    def provider_name(self) -> str:
        return "Codex"

    def get_credentials(self) -> CodexTokens:
        """Read the OAuth token dict for this account.

        When ``account_id=="default"``, reads from the standard Codex
        CLI auth file (``~/.codex/auth.json``).
        Otherwise reads from the cockpit-tools account file
        (``codex_accounts/<id>.json``).
        """
        if self.account_id == "default":
            data: dict[str, Any] = json.loads((Path.home() / ".codex" / "auth.json").read_text())
            return cast(CodexTokens, data["tokens"])

        # Cockpit V2 path — look up the account entry by email
        index = cast(CodexAccountIndex, json.loads(CODEX_ACCOUNTS_INDEX_PATH.read_text()))
        entry_id: str | None = None
        for entry in index["accounts"]:
            if entry["email"] == self.account_id:
                entry_id = entry["id"]
                break
        if entry_id is None:
            raise KeyError(f"Codex account {self.account_id!r} not found in cockpit index")
        acct_file = cast(
            CodexAccountFile,
            json.loads((CODEX_ACCOUNTS_DIR / f"{entry_id}.json").read_text()),
        )
        return acct_file["tokens"]

    def fetch_raw(self) -> WhamUsageResponse:
        creds = self.get_credentials()
        resp = requests.get(
            "https://chatgpt.com/backend-api/wham/usage",
            headers={"Authorization": f"Bearer {creds['access_token']}"},
            timeout=30,
        )
        resp.raise_for_status()
        return cast(WhamUsageResponse, resp.json())

    def to_rows(self, raw: WhamUsageResponse) -> list[UsageRow]:
        rate_limit = raw["rate_limit"]
        primary = rate_limit["primary_window"]
        secondary = rate_limit["secondary_window"]

        rows: list[UsageRow] = [
            UsageRow(
                identifier="Codex (5h)",
                pct_used=primary["used_percent"],
                reset_at=_ts_to_dt(primary["reset_at"]),
            ),
        ]
        if secondary:
            rows.append(
                UsageRow(
                    identifier="Codex (7d)",
                    pct_used=secondary["used_percent"],
                    reset_at=_ts_to_dt(secondary["reset_at"]),
                )
            )
        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        if any(r.is_exhausted for r in rows):
            return False
        return any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
        if self.should_anchor(rows):
            self.send_ntfy(
                "Codex Window Open",
                "Codex 5h window open!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str]:
        return ["codex", "exec", "-c", "project_doc_max_bytes=0", "Say hello and do nothing else"]

    @classmethod
    def resolve_accounts(cls) -> list[CodexProvider]:
        """Return one ``CodexProvider`` per cockpit-tools Codex account."""
        index = cast(CodexAccountIndex, json.loads(CODEX_ACCOUNTS_INDEX_PATH.read_text()))
        return [cls(entry["email"]) for entry in index["accounts"]]


def _ts_to_dt(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)
