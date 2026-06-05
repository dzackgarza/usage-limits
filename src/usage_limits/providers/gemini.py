"""Gemini CLI usage limits provider.

Uses cockpit-tools credential storage for account discovery and OAuth
tokens. Reads the following files from ``~/.antigravity_cockpit/``:

=========================== ===============================================
File                        Role
=========================== ===============================================
``gemini_accounts.json``    Gemini account index — lists every known Gemini
                            account with a UUID, email, and name.
                            Read by ``resolve_accounts()``.
``gemini_accounts/<id>.json``  Per-account credential file.
                            Contains OAuth tokens (``access_token``,
                            ``refresh_token``), ``project_id``, and
                            cached ``gemini_usage_raw``.
=========================== ===============================================

Each account independently refreshes its own OAuth token and fetches quota
from the Gemini ``retrieveUserQuota`` endpoint (not Antigravity's
``loadCodeAssist`` + ``fetchAvailableModels`` flow).

The OAuth client ID and secret are hardcoded in config — they match the
values embedded in cockpit-tools ``gemini_oauth.rs``. These are public;
the actual secret is each account's refresh token.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.config import resolve_path
from usage_limits.table import ModelAvailability, UsageRow

# ---------------------------------------------------------------------------
# TypedDicts
# ---------------------------------------------------------------------------


class GeminiAccountFile(TypedDict):
    """Per-account credential file from cockpit-tools Gemini storage.

    The real on-disk format stores OAuth fields as top-level keys
    (not nested under a ``token`` dict).
    """

    id: str
    email: str
    auth_id: str
    name: str
    access_token: str
    refresh_token: str
    id_token: str
    token_type: str
    scope: str
    expiry_date: int  # milliseconds since epoch
    selected_auth_type: str
    project_id: str
    tier_id: str
    plan_name: str
    gemini_auth_raw: dict[str, Any]
    gemini_usage_raw: dict[str, Any]
    usage_updated_at: int
    created_at: int
    last_used: int


class GeminiAccountEntry(TypedDict):
    id: str
    email: str
    name: str
    created_at: int
    last_used: int


class GeminiAccountIndex(TypedDict):
    version: float
    accounts: list[GeminiAccountEntry]
    current_account_id: str | None


class TokenResponse(TypedDict):
    access_token: str
    expires_in: int
    token_type: str


class BucketInfo(TypedDict):
    modelId: str
    remainingFraction: float
    resetTime: str
    tokenType: str


class RetrieveQuotaResponse(TypedDict, total=False):
    buckets: list[BucketInfo]


class GeminiRaw(TypedDict):
    buckets: list[BucketInfo]


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class GeminiAccount(ProviderAccount):
    """Gemini CLI usage checker for a single account.

    One instance per credential email. Use ``resolve_accounts()`` to
    discover all accounts from the cockpit-tools Gemini file layout
    (``gemini_accounts.json`` + ``gemini_accounts/<uuid>.json``).
    """

    slug = "gemini-cli"
    name = "Gemini CLI"
    state_dir = "gemini_cli_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self, account_id: str) -> None:
        super().__init__(account_id=account_id)

    def provider_name(self) -> str:
        return "Gemini CLI"

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_paths() -> tuple[Any, Any]:
        """Resolve cockpit-tools gemini account paths from config."""
        from usage_limits.config import settings as _cfg

        index_path = resolve_path(_cfg.paths.gemini_cockpit_accounts_index)
        accounts_dir = resolve_path(_cfg.paths.gemini_cockpit_accounts_dir)
        return index_path, accounts_dir

    @staticmethod
    def _read_account_file(email: str) -> GeminiAccountFile:
        """Read the per-account credential file for the given email."""
        index_path, accounts_dir = GeminiAccount._resolve_paths()
        index = cast(GeminiAccountIndex, json.loads(index_path.read_text()))
        uuid: str | None = None
        for entry in index["accounts"]:
            if entry["email"] == email:
                uuid = entry["id"]
                break
        if uuid is None:
            raise KeyError(f"Gemini account {email!r} not found in cockpit-tools account index")
        return cast(
            GeminiAccountFile,
            json.loads((accounts_dir / f"{uuid}.json").read_text()),
        )

    # ------------------------------------------------------------------
    # OAuth / API
    # ------------------------------------------------------------------

    def _get_access_token(self) -> str:
        """Refresh the OAuth access token for ``self.account_id``."""
        from usage_limits.config import settings as _cfg

        acct = self._read_account_file(self.account_id)
        resp = requests.post(
            _cfg.gemini.oauth_token_endpoint,
            json={
                "client_id": _cfg.gemini.client_id,
                "client_secret": _cfg.gemini.client_secret,
                "refresh_token": acct["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        return cast(TokenResponse, resp.json())["access_token"]

    def _fetch_quota(self, access_token: str) -> GeminiRaw:
        """Fetch per-model quota buckets for the given account."""
        from usage_limits.config import settings as _cfg

        acct = self._read_account_file(self.account_id)
        project_id = acct["project_id"]

        headers: dict[str, str] = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            f"{_cfg.gemini.cloudcode_base_url}/v1internal:retrieveUserQuota",
            headers=headers,
            json={"project": project_id},
        )
        quota_resp = cast(RetrieveQuotaResponse, resp.json())
        return cast(GeminiRaw, {"buckets": quota_resp.get("buckets", [])})

    # ------------------------------------------------------------------
    # Provider interface
    # ------------------------------------------------------------------

    def fetch_raw(self) -> GeminiRaw:
        token = self._get_access_token()
        return self._fetch_quota(token)

    @staticmethod
    def _bucket_model_name(bucket: BucketInfo) -> str:
        """Extract a short human-readable model name from a bucket modelId.

        E.g. ``models/gemini-2.0-flash`` → ``Gemini 2.0 Flash``.
        """
        model_id = bucket["modelId"]
        # Strip "models/" prefix
        name = model_id.removeprefix("models/")
        # Replace hyphens with spaces and title-case
        name = name.replace("-", " ").title()
        return name

    def to_rows(self, raw: GeminiRaw) -> list[UsageRow]:
        rows: list[UsageRow] = []
        for bucket in raw["buckets"]:
            label = self._bucket_model_name(bucket)
            remaining = bucket["remainingFraction"]
            pct_used = round((1.0 - remaining) * 100.0)

            reset_time = bucket.get("resetTime", "")
            if reset_time:
                reset_at = datetime.fromisoformat(reset_time.replace("Z", "+00:00")).astimezone(UTC)
            else:
                reset_at = None

            rows.append(
                UsageRow(
                    identifier=label,
                    pct_used=pct_used,
                    reset_at=reset_at,
                )
            )

        # Sort alphabetically by model name
        rows.sort(key=lambda r: r.identifier)
        return rows

    def availability(self, rows: list[UsageRow]) -> list[ModelAvailability]:
        if not rows:
            return []
        # Use the most-used model as the proxy for overall availability
        max_used = max(rows, key=lambda r: r.pct_used)
        available_now = max_used.pct_used < 99.0
        return [
            ModelAvailability(
                name="Gemini CLI",
                available_now=available_now,
                available_when=None if available_now else max_used.reset_at,
            )
        ]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        if rows and all(row.pct_used < 1.0 for row in rows):
            self.send_ntfy(
                "Gemini CLI Quota Fresh",
                "All Gemini CLI models are below 1% used.",
                tags="white_check_mark,rocket",
            )

    # ------------------------------------------------------------------
    # Account discovery
    # ------------------------------------------------------------------

    @classmethod
    def resolve_accounts(cls) -> Sequence[GeminiAccount]:
        """Return one ``GeminiAccount`` per credential email.

        Reads the cockpit-tools ``gemini_accounts.json`` index and returns
        one instance per account.
        """
        index_path, _ = cls._resolve_paths()
        index = cast(GeminiAccountIndex, json.loads(index_path.read_text()))
        return [cls(entry["email"]) for entry in index["accounts"]]


# Backward-compat alias
GeminiProvider = GeminiAccount
