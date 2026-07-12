"""Provider for Codex usage metrics.

Reads OAuth tokens exclusively from the app-owned CredentialStore.
This provider is fully independent of the Codex CLI and its auth file
(``~/.codex/auth.json``). It works even if Codex CLI is not installed.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

if TYPE_CHECKING:
    from usage_limits.auth.oauth import LocalhostBrowserFlow, OAuthReauthRequiredError
    from usage_limits.auth.store import CredentialStore, StoredCredential

import requests

from usage_limits.base import ProviderAccount
from usage_limits.table import UsageRow


class CodexTokens(TypedDict):
    access_token: str
    refresh_token: str
    id_token: str


class WhamWindow(TypedDict):
    used_percent: float
    reset_at: int | None


class WhamWindowWithWindowSeconds(WhamWindow, total=False):
    limit_window_seconds: int | None


class WhamRateLimit(TypedDict):
    primary_window: WhamWindow
    secondary_window: WhamWindow | None


class AdditionalCodexRateLimit(TypedDict):
    limit_name: str
    metered_feature: str
    rate_limit: WhamRateLimit


class WhamUsageResponse(TypedDict):
    rate_limit: WhamRateLimit
    additional_rate_limits: NotRequired[list[AdditionalCodexRateLimit] | None]


class CodexProvider(ProviderAccount):
    """Codex CLI usage checker (5-hour and 7-day WHAM windows).

    One instance per credential email. Use ``resolve_accounts()`` to
    discover all accounts from CredentialStore.
    """

    slug = "codex"
    name = "Codex"
    state_dir = "codex_usage"

    def __init__(self, account_id: str) -> None:
        super().__init__(account_id=account_id)

    def provider_name(self) -> str:
        return "Codex"

    def get_credentials(self) -> CodexTokens:
        """Read the OAuth token dict for this account from CredentialStore."""
        from usage_limits.auth.store import CredentialStore

        store = CredentialStore()
        cred = store.get("codex", self.account_id)
        self._raise_if_reauth_required(cred)

        refresh_token = cred["refresh_token"]
        assert refresh_token is not None, f"No refresh token for codex account {self.account_id}"
        return cast(
            CodexTokens,
            {
                "access_token": cred["access_token"],
                "refresh_token": refresh_token,
                "id_token": cred.get("extra", {}).get("id_token", ""),
            },
        )

    def _raise_if_reauth_required(self, cred: StoredCredential) -> None:
        if "requires_reauth" in cred:
            assert cred["requires_reauth"] is True, (
                f"Unexpected false reauth marker for codex account {self.account_id}"
            )
            from usage_limits.auth.oauth import OAuthReauthRequiredError

            raise OAuthReauthRequiredError(
                status_code=cred["reauth_status_code"],
                error_code=cred["reauth_error_code"],
                error_message=(
                    f"Codex account {self.account_id} requires `usage-limits login codex`."
                ),
            )

    def _make_flow(self) -> LocalhostBrowserFlow:
        from usage_limits.auth.oauth import LocalhostBrowserFlow

        return LocalhostBrowserFlow(
            client_id="app_EMoamEEZ73f0CkXaXp7hrann",
            client_secret=None,
            scopes=[],
            auth_url="https://auth.openai.com/oauth/authorize",
            token_url="https://auth.openai.com/oauth/token",
        )

    def _save_store_credentials(
        self, access_token: str, refresh_token: str, expires_at: str | None
    ) -> None:
        from usage_limits.auth.store import CredentialStore, StoredCredential

        cred = cast(
            StoredCredential,
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "email": self.account_id,
            },
        )
        CredentialStore().save("codex", self.account_id, cred)

    def _mark_reauth_required(
        self,
        store: CredentialStore,
        cred: StoredCredential,
        error: OAuthReauthRequiredError,
    ) -> None:
        cred["requires_reauth"] = True
        cred["reauth_error_code"] = error.error_code
        cred["reauth_status_code"] = error.status_code
        cred["reauth_at"] = datetime.now(UTC).isoformat()
        store.save("codex", self.account_id, cred)

    def _refresh_store(self) -> str:
        """Refresh a CredentialStore account's tokens."""
        from usage_limits.auth.oauth import OAuthReauthRequiredError
        from usage_limits.auth.store import CredentialStore

        store = CredentialStore()
        cred = store.get("codex", self.account_id)
        self._raise_if_reauth_required(cred)

        refresh_token = cred["refresh_token"]
        assert refresh_token is not None, f"No refresh token for codex account {self.account_id}"

        try:
            result = self._make_flow().refresh(refresh_token)
        except OAuthReauthRequiredError as error:
            self._mark_reauth_required(store, cred, error)
            raise

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
            new_token = self._refresh_store()

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

        primary_window = cast(WhamWindowWithWindowSeconds, primary)
        rows: list[UsageRow] = [
            UsageRow(
                identifier=f"Codex ({_window_label(primary_window, '5h')})",
                pct_used=round(primary["used_percent"]),
                reset_at=_ts_to_dt(primary["reset_at"]),
            ),
        ]
        if secondary:
            secondary_window = cast(WhamWindowWithWindowSeconds, secondary)
            rows.append(
                UsageRow(
                    identifier=f"Codex ({_window_label(secondary_window, '7d')})",
                    pct_used=round(secondary["used_percent"]),
                    reset_at=_ts_to_dt(secondary["reset_at"]),
                )
            )

        if "additional_rate_limits" in raw and raw["additional_rate_limits"] is not None:
            for additional in raw["additional_rate_limits"]:
                limit_name = additional["limit_name"].replace("-", " ")
                codex_idx = limit_name.find("Codex")
                limit_label = limit_name[codex_idx:] if codex_idx != -1 else limit_name

                additional_rate_limit = additional["rate_limit"]
                additional_primary = additional_rate_limit["primary_window"]
                additional_secondary = additional_rate_limit["secondary_window"]
                primary_window = cast(WhamWindowWithWindowSeconds, additional_primary)

                rows.append(
                    UsageRow(
                        identifier=f"{limit_label} ({_window_label(primary_window, '5d')})",
                        pct_used=round(additional_primary["used_percent"]),
                        reset_at=_ts_to_dt(additional_primary["reset_at"]),
                    )
                )
                if additional_secondary:
                    secondary_window = cast(WhamWindowWithWindowSeconds, additional_secondary)
                    rows.append(
                        UsageRow(
                            identifier=(f"{limit_label} ({_window_label(secondary_window, '7d')})"),
                            pct_used=round(additional_secondary["used_percent"]),
                            reset_at=_ts_to_dt(additional_secondary["reset_at"]),
                        )
                    )
        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        weekly_rows = {
            row.identifier.removesuffix(" (7d)"): row
            for row in rows
            if row.identifier.endswith(" (7d)")
        }
        for row in rows:
            if row.pct_used != 0 or not row.identifier.endswith(" (5h)"):
                continue
            bucket = row.identifier.removesuffix(" (5h)")
            if bucket in weekly_rows and not weekly_rows[bucket].is_exhausted:
                return True
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        if self.should_anchor(rows):
            self.send_ntfy(
                "Codex Window Open",
                "Codex 5h window open!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str]:
        return [
            "codex",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "-c",
            "project_doc_max_bytes=0",
            "Reply exactly: ok",
        ]

    def _anchor_window(self, command: list[str]) -> bool:
        creds = self.get_credentials()
        env = os.environ.copy()
        with tempfile.TemporaryDirectory() as codex_home:
            env["CODEX_HOME"] = codex_home
            login = subprocess.run(
                ["codex", "login", "--with-access-token"],
                input=f"{creds['access_token']}\n",
                cwd=codex_home,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if login.returncode != 0:
                return False

            result = subprocess.run(
                command,
                cwd=codex_home,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0

    @classmethod
    def resolve_accounts(cls) -> Sequence[CodexProvider]:
        """Return one ``CodexProvider`` per stored Codex credential, sorted by mtime."""
        from usage_limits.auth.store import CredentialStore

        store = CredentialStore()
        accounts = store.list_accounts("codex")

        if not accounts:
            return []

        account_priority: dict[str, tuple[int, float]] = {}
        for email in accounts:
            path = store._credential_path("codex", email)
            cred = store.get("codex", email)
            reauth_rank = 1 if "requires_reauth" in cred else 0
            account_priority[email] = (reauth_rank, path.stat().st_mtime)

        sorted_accounts = sorted(
            account_priority,
            key=lambda account_id: (
                account_priority[account_id][0],
                -account_priority[account_id][1],
            ),
        )
        return [cls(email) for email in sorted_accounts]


def _ts_to_dt(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


def _window_label(window: WhamWindowWithWindowSeconds, fallback: str) -> str:
    if "limit_window_seconds" in window:
        limit_window_seconds = window["limit_window_seconds"]
        if limit_window_seconds is not None:
            if limit_window_seconds % 86400 == 0:
                return f"{limit_window_seconds // 86400}d"
            if limit_window_seconds % 3600 == 0:
                return f"{limit_window_seconds // 3600}h"
    return fallback
