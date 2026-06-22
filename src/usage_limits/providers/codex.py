"""Provider for Codex usage metrics.

Reads OAuth tokens from the credential store and fallbacks.

========================= ===========================================
File                      Role
========================= ===========================================
``credentials/codex/``    CredentialStore backend directory.
                          Contains OAuth tokens.
========================= ===========================================

When constructed directly (``account_id="default"``), falls back to
``~/.codex/auth.json`` for backward compatibility with the standard
Codex CLI auth file.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypedDict, cast

if TYPE_CHECKING:
    from usage_limits.auth.oauth import LocalhostBrowserFlow

import requests

from usage_limits.base import ProviderAccount
from usage_limits.config import resolve_path
from usage_limits.table import UsageRow


class CodexTokens(TypedDict):
    access_token: str
    refresh_token: str
    id_token: str
    account_id: str


class CodexCredentials(TypedDict):
    access_token: str


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
    discover all accounts from CredentialStore.
    """

    slug = "codex"
    name = "Codex"
    state_dir = "codex_usage"

    def __init__(self, account_id: str = "default") -> None:
        super().__init__(account_id=account_id)

    def provider_name(self) -> str:
        return "Codex"

    def get_credentials(self) -> CodexTokens:
        """Read the OAuth token dict for this account.

        When ``account_id=="default"``, reads from the standard Codex
        CLI auth file (``~/.codex/auth.json``).
        Otherwise reads from the CredentialStore.
        """
        if self.account_id == "default":
            from usage_limits.config import settings as _cfg

            data: dict[str, Any] = json.loads(resolve_path(_cfg.paths.codex_auth).read_text())
            return cast(CodexTokens, data["tokens"])

        from usage_limits.auth.store import CredentialStore

        store = CredentialStore()
        try:
            cred = store.get("codex", self.account_id)
            return cast(
                CodexTokens,
                {
                    "access_token": cred["access_token"],
                    "refresh_token": cred["refresh_token"],
                    "id_token": "",
                    "account_id": self.account_id,
                },
            )
        except FileNotFoundError as e:
            raise KeyError(f"Codex account {self.account_id!r} not found in CredentialStore") from e

    def _make_flow(self) -> LocalhostBrowserFlow:
        from usage_limits.auth.oauth import LocalhostBrowserFlow

        return LocalhostBrowserFlow(
            client_id="app_EMoamEEZ73f0CkXaXp7hrann",
            client_secret=None,
            scopes=[],
            auth_url="https://auth.openai.com/oauth/authorize",
            token_url="https://auth.openai.com/oauth/token",
        )

    def _refresh_default(self, e: requests.HTTPError) -> str:
        """Refresh the default account's tokens in ~/.codex/auth.json."""
        from usage_limits.config import settings as _cfg

        auth_path = resolve_path(_cfg.paths.codex_auth)
        data: dict[str, Any] = json.loads(auth_path.read_text())
        tokens = data["tokens"]

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("No refresh token in ~/.codex/auth.json") from e

        result = self._make_flow().refresh(refresh_token)

        tokens["access_token"] = result["access_token"]
        if result["new_refresh_token"] is not None:
            tokens["refresh_token"] = result["new_refresh_token"]
        auth_path.write_text(json.dumps(data))

        return result["access_token"]

    def _refresh_store(self, e: requests.HTTPError) -> str:
        """Refresh a CredentialStore account's tokens."""
        from usage_limits.auth.store import CredentialStore

        store = CredentialStore()
        cred = store.get("codex", self.account_id)

        refresh_token = cred.get("refresh_token")
        if not refresh_token:
            raise RuntimeError(
                f"No refresh token available for codex account {self.account_id}"
            ) from e

        result = self._make_flow().refresh(refresh_token)

        cred["access_token"] = result["access_token"]
        cred["expires_at"] = result["expires_at"]
        if result["new_refresh_token"] is not None:
            cred["refresh_token"] = result["new_refresh_token"]
        store.save("codex", self.account_id, cred)

        return result["access_token"]

    def fetch_raw(self) -> WhamUsageResponse:
        from usage_limits.config import settings as _cfg

        creds = self.get_credentials()
        resp = requests.get(
            _cfg.codex.api_url,
            headers={"Authorization": f"Bearer {creds['access_token']}"},
            timeout=30,
        )

        if resp.status_code == 401:
            if self.account_id == "default":
                new_token = self._refresh_default(requests.HTTPError(response=resp))
            else:
                new_token = self._refresh_store(requests.HTTPError(response=resp))

            resp = requests.get(
                _cfg.codex.api_url,
                headers={"Authorization": f"Bearer {new_token}"},
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
                pct_used=round(primary["used_percent"]),
                reset_at=_ts_to_dt(primary["reset_at"]),
            ),
        ]
        if secondary:
            rows.append(
                UsageRow(
                    identifier="Codex (7d)",
                    pct_used=round(secondary["used_percent"]),
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
    def resolve_accounts(cls) -> Sequence[CodexProvider]:
        """Return one ``CodexProvider`` per CredentialStore Codex account."""
        from usage_limits.auth.store import CredentialStore

        store = CredentialStore()
        return [cls(email) for email in store.list_accounts("codex")]


def _ts_to_dt(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)
