"""Provider for Codex usage metrics.

Reads OAuth tokens from the credential store and the Codex CLI auth file.

========================= ===========================================
File                      Role
========================= ===========================================
``credentials/codex/``    CredentialStore backend directory.
                          Contains OAuth tokens.
``~/.codex/auth.json``    Codex CLI auth file. Identified by the email
                          claim in its ID token.
========================= ===========================================
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

if TYPE_CHECKING:
    from usage_limits.auth.oauth import LocalhostBrowserFlow, OAuthReauthRequiredError
    from usage_limits.auth.store import CredentialStore, StoredCredential

import requests

from usage_limits.base import ProviderAccount
from usage_limits.config import resolve_path
from usage_limits.table import UsageRow


class CodexTokens(TypedDict):
    access_token: str
    refresh_token: str
    id_token: str


class CodexCliTokens(CodexTokens):
    account_id: str


class CodexAuthFile(TypedDict):
    tokens: CodexCliTokens


class CodexIdTokenPayload(TypedDict):
    email: str


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
        """Read the OAuth token dict for this account.

        If the standard Codex CLI auth file identifies this account's
        email, it is the freshest credential source for that account.
        Otherwise reads from the CredentialStore.
        """
        from usage_limits.auth.store import CredentialStore

        store = CredentialStore()
        try:
            cred = store.get("codex", self.account_id)
            self._raise_if_reauth_required(cred)
        except FileNotFoundError:
            cred = None

        if self._codex_auth_matches_account():
            return self._read_codex_auth()["tokens"]

        if cred is not None:
            refresh_token = cred["refresh_token"]
            assert refresh_token is not None, (
                f"No refresh token for codex account {self.account_id}"
            )
            return cast(
                CodexTokens,
                {
                    "access_token": cred["access_token"],
                    "refresh_token": refresh_token,
                    "id_token": "",
                },
            )
        raise KeyError(f"Codex account {self.account_id!r} not found in CredentialStore")

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
                    f"Codex account {self.account_id} requires "
                    "`usage-limits login codex`."
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

    @staticmethod
    def _email_from_id_token(id_token: str) -> str:
        parts = id_token.split(".")
        assert len(parts) == 3, f"Codex ID token must be a JWT; found {len(parts)} parts"
        payload_segment = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
        payload = cast(
            CodexIdTokenPayload,
            json.loads(base64.urlsafe_b64decode(payload_segment)),
        )
        email = payload["email"]
        assert email, "Codex ID token email claim must be non-empty"
        return email

    @classmethod
    def _read_codex_auth(cls) -> CodexAuthFile:
        from usage_limits.config import settings as _cfg

        auth_path = resolve_path(_cfg.paths.codex_auth)
        return cast(CodexAuthFile, json.loads(auth_path.read_text()))

    @classmethod
    def _codex_auth_email(cls) -> str:
        return cls._email_from_id_token(cls._read_codex_auth()["tokens"]["id_token"])

    def _codex_auth_matches_account(self) -> bool:
        from usage_limits.config import settings as _cfg

        auth_path = resolve_path(_cfg.paths.codex_auth)
        if not auth_path.exists():
            return False
        return self._codex_auth_email() == self.account_id

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

    def _refresh_codex_auth(self) -> str:
        """Refresh the Codex CLI auth file's tokens."""
        from usage_limits.auth.oauth import OAuthReauthRequiredError
        from usage_limits.auth.store import CredentialStore, StoredCredential
        from usage_limits.config import settings as _cfg

        auth_path = resolve_path(_cfg.paths.codex_auth)
        data = self._read_codex_auth()
        tokens = data["tokens"]

        try:
            result = self._make_flow().refresh(tokens["refresh_token"])
        except OAuthReauthRequiredError as error:
            cred = cast(
                StoredCredential,
                {
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "expires_at": None,
                    "email": self.account_id,
                },
            )
            self._mark_reauth_required(CredentialStore(), cred, error)
            raise

        tokens["access_token"] = result["access_token"]
        if result["new_refresh_token"] is not None:
            tokens["refresh_token"] = result["new_refresh_token"]
        auth_path.write_text(json.dumps(data))
        self._save_store_credentials(
            result["access_token"], tokens["refresh_token"], result["expires_at"]
        )

        return result["access_token"]

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
            if self._codex_auth_matches_account():
                new_token = self._refresh_codex_auth()
            else:
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
                            identifier=(
                                f"{limit_label} "
                                f"({_window_label(secondary_window, '7d')})"
                            ),
                            pct_used=round(additional_secondary["used_percent"]),
                            reset_at=_ts_to_dt(additional_secondary["reset_at"]),
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
        """Return one ``CodexProvider`` per resolved Codex credential.

        Resolution prefers the most recently used credential source:
        - Active CLI-auth email first (if present and freshest).
        - Other stored accounts by credential file mtime descending.
        """
        from usage_limits.auth.store import CredentialStore

        store = CredentialStore()
        accounts = store.list_accounts("codex")

        account_priority: dict[str, tuple[int, float]] = {}
        for email in accounts:
            path = store._credential_path("codex", email)
            cred = store.get("codex", email)
            reauth_rank = 1 if "requires_reauth" in cred else 0
            account_priority[email] = (reauth_rank, path.stat().st_mtime)

        from usage_limits.config import settings as _cfg

        auth_path = resolve_path(_cfg.paths.codex_auth)
        if auth_path.exists():
            auth_email = cls._codex_auth_email()
            if auth_email not in account_priority or account_priority[auth_email][0] == 0:
                account_priority[auth_email] = (0, auth_path.stat().st_mtime)

        if not account_priority:
            return []

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
