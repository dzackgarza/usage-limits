"""Antigravity usage limits provider.

Depends on cockpit-tools (https://github.com/jlcodes99/cockpit-tools)
for credential storage. Reads the following files from
``~/.antigravity_cockpit/``:

==================== ===============================================
File                 Role
==================== ===============================================
``accounts.json``    V2 account index — lists every known account
                     with a UUID, email, name, and timestamps.
                     Read by ``resolve_accounts()`` to discover
                     which accounts exist.
``accounts/<id>.json``  Per-account credential file (one per UUID).
                     Contains the OAuth ``token`` dict (with
                     ``refresh_token``) plus a ``disabled`` flag.
                     Read by ``_get_access_token()`` to obtain the
                     refresh token for each account.
``credentials.json`` Legacy V1 file (no longer read). Stored only
                     the active account.
==================== ===============================================

Account resolution:
  ``resolve_accounts()`` parses ``accounts.json``, reads each
  account's individual file, skips those with ``"disabled": true``,
  and returns one ``AntigravityAccount(email)`` per remaining entry.
  Each instance independently refreshes its own OAuth token and
  fetches quota from the Google Cloud Code API.

The OAuth client ID and secret are hardcoded — they match the values
embedded in cockpit-tools
``src-tauri/src/modules/oauth.rs``). These are public; the actual
secret is each account's refresh token.

Known upstream quirk:
Anthropic models (Claude Sonnet, Opus, GPT-OSS) stopped including
``remainingPercentage`` and report ``isExhausted: false`` even when
they are fully exhausted. We treat a missing ``remainingPercentage``
as 100% used regardless of the ``isExhausted`` field.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.config import resolve_path
from usage_limits.table import ModelAvailability, UsageRow

# Default cockpit directory — override via config
_COCKPIT_DIR_STR = "~/.antigravity_cockpit"
_COCKPIT_DIR = resolve_path(_COCKPIT_DIR_STR)
COCKPIT_CREDENTIALS_PATH = _COCKPIT_DIR / "credentials.json"  # V1 legacy, one account only
ACCOUNTS_INDEX_PATH = _COCKPIT_DIR / "accounts.json"  # V2 account index
ACCOUNTS_DIR = _COCKPIT_DIR / "accounts"  # V2 per-account credential files


class AntigravityModel(TypedDict):
    label: str
    modelId: str
    remainingPercentage: NotRequired[float]  # absent -> tool bug -> treat as exhausted
    isExhausted: bool
    resetTime: str | None
    accountEmail: str


class AntigravityRaw(TypedDict):
    models: list[AntigravityModel]


class CockpitAccount(TypedDict):
    email: str
    accessToken: str
    refreshToken: str
    expiresAt: str
    projectId: str


class CockpitCredentials(TypedDict):
    accounts: dict[str, CockpitAccount]


class TokenResponse(TypedDict):
    access_token: str
    expires_in: int
    token_type: str


class LoadCodeAssistResponse(TypedDict, total=False):
    codeAssistEnabled: bool
    planInfo: dict[str, object]
    availablePromptCredits: float
    cloudaicompanionProject: str | dict[str, str]
    currentTier: dict[str, str]
    paidTier: dict[str, str]
    allowedTiers: list[dict[str, str]]


class ModelQuotaInfo(TypedDict, total=False):
    remainingFraction: float
    resetTime: str
    isExhausted: bool


class ModelInfo(TypedDict, total=False):
    displayName: str
    model: str
    label: str
    quotaInfo: ModelQuotaInfo
    maxTokens: int
    recommended: bool
    supportsImages: bool
    supportsThinking: bool
    modelProvider: str


class FetchAvailableModelsResponse(TypedDict, total=False):
    models: dict[str, ModelInfo]
    defaultAgentModelId: str


class V2AccountEntry(TypedDict):
    id: str
    email: str
    name: str
    created_at: int
    last_used: int


class V2AccountIndex(TypedDict):
    version: float
    accounts: list[V2AccountEntry]
    current_account_id: str | None


class V2Token(TypedDict):
    access_token: str
    refresh_token: str
    expires_in: int
    expiry_timestamp: int
    token_type: str
    email: str


class V2AccountFile(TypedDict):
    id: str
    email: str
    name: str
    token: V2Token
    fingerprint_id: str
    disabled: bool
    quota_error: NotRequired[dict[str, Any]]
    usage_updated_at: int
    created_at: int
    last_used: int


class AntigravityAccount(ProviderAccount):
    """Antigravity usage checker for a single account.

    One instance per credential email. Use ``resolve_accounts()`` to
    discover all accounts from the V2 cockpit-tools file layout
    (``accounts.json`` + ``accounts/<uuid>.json``).
    """

    slug = "antigravity"
    name = "Antigravity"
    state_dir = "antigravity_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self, account_id: str) -> None:
        super().__init__(account_id=account_id)

    def provider_name(self) -> str:
        return "Antigravity"

    @staticmethod
    def _read_account_token(email: str) -> V2Token:
        """Read the token dict for an account email from V2 account files.

        Looks up the account UUID in ``accounts.json``, then reads
        ``accounts/<uuid>.json`` to get the OAuth token.
        """
        index = cast(V2AccountIndex, json.loads(ACCOUNTS_INDEX_PATH.read_text()))
        uuid: str | None = None
        for entry in index["accounts"]:
            if entry["email"] == email:
                uuid = entry["id"]
                break
        if uuid is None:
            raise KeyError(f"Account {email!r} not found in cockpit accounts index")
        acct_file = cast(V2AccountFile, json.loads((ACCOUNTS_DIR / f"{uuid}.json").read_text()))
        return acct_file["token"]

    def _get_access_token(self) -> str:
        """Get a fresh access token for ``self.account_id``."""
        from usage_limits.config import settings as _cfg

        token = self._read_account_token(self.account_id)
        resp = requests.post(
            _cfg.antigravity.oauth_token_endpoint,
            json={
                "client_id": _cfg.antigravity.client_id,
                "client_secret": _cfg.antigravity.client_secret,
                "refresh_token": token["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        return cast(TokenResponse, resp.json())["access_token"]

    def _fetch_models(self, token: str) -> list[AntigravityModel]:
        """Fetch and parse model quota data for this account."""
        from usage_limits.config import settings as _cfg

        headers: dict[str, str] = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "antigravity",
        }

        cfg = _cfg.antigravity

        # Step 1: Load code assist (gets plan info, project ID)
        resp = requests.post(
            f"{cfg.cloudcode_base_url}/v1internal:loadCodeAssist",
            headers=headers,
            json={
                "metadata": {
                    "ideType": cfg.metadata_ide_type,
                    "platform": cfg.metadata_platform,
                    "pluginType": cfg.metadata_plugin_type,
                }
            },
        )
        code_assist = cast(LoadCodeAssistResponse, resp.json())

        # Extract project ID
        project_info = code_assist.get("cloudaicompanionProject")
        project_id: str | None = None
        if isinstance(project_info, str):
            project_id = project_info
        elif isinstance(project_info, dict):
            project_id = project_info.get("id")

        # Step 2: Fetch available models (gets per-model quota)
        body: dict[str, object] = {}
        if project_id:
            body["project"] = project_id

        resp = requests.post(
            f"{cfg.cloudcode_base_url}/v1internal:fetchAvailableModels",
            headers=headers,
            json=body,
        )
        models_data = cast(FetchAvailableModelsResponse, resp.json())

        # Convert to the raw format that to_rows expects
        # Deduplicate by label and filter out deprecated/experimental models
        seen_labels: set[str] = set()
        models: list[AntigravityModel] = []
        for model_id, info in models_data.get("models", {}).items():
            label = info.get("label", info.get("displayName", model_id))

            # Skip internal/experimental models
            if label.startswith(("chat_", "tab_", "gemini-")):
                continue
            # Skip deprecated models
            if label in cfg.deprecated_models:
                continue
            # Skip duplicates within this account (keep first seen)
            if label in seen_labels:
                continue
            seen_labels.add(label)

            quota = info.get("quotaInfo", {})
            reset_time = quota.get("resetTime")
            is_exhausted = quota.get("isExhausted", False)

            model: AntigravityModel = {
                "label": label,
                "modelId": model_id,
                "isExhausted": is_exhausted,
                "resetTime": reset_time,
                "accountEmail": self.account_id,
            }

            remaining = quota.get("remainingFraction")
            if remaining is not None:
                model["remainingPercentage"] = remaining

            models.append(model)

        return models

    def fetch_raw(self) -> AntigravityRaw:
        token = self._get_access_token()
        models = self._fetch_models(token)
        return cast(AntigravityRaw, {"models": models})

    @staticmethod
    def _model_sort_key(identifier: str) -> tuple[int, int, str]:
        """Sort key: all Gemini (Flash before Pro) first, then Claude, then GPT OSS."""
        label = identifier.lower()
        if "gemini" in label or label.startswith(("flash", "pro", "2.5", "3")):
            sub = 0 if "flash" in label else 1
            return 0, sub, label
        if "claude" in label:
            return 1, 0, label
        if "gpt-oss" in label or "gpt oss" in label:
            return 2, 0, label
        return 3, 0, label

    def to_rows(self, raw: AntigravityRaw) -> list[UsageRow]:
        rows: list[UsageRow] = []
        for model in raw["models"]:
            label = model["label"]
            remaining_percentage = model.get("remainingPercentage")  # absent = tool bug = exhausted
            is_exhausted = model["isExhausted"]
            if remaining_percentage is None or is_exhausted:
                pct_used = 100.0
            else:
                pct_used = (1.0 - remaining_percentage) * 100.0

            reset_time = model["resetTime"]
            if reset_time:
                reset_at = datetime.fromisoformat(reset_time.replace("Z", "+00:00")).astimezone(UTC)
            else:
                reset_at = None

            rows.append(
                UsageRow(
                    identifier=label,
                    pct_used=round(pct_used),
                    reset_at=reset_at,
                )
            )

        rows.sort(key=lambda r: self._model_sort_key(r.identifier))
        return rows

    def availability(self, rows: list[UsageRow]) -> list[ModelAvailability]:
        buckets: list[tuple[str, tuple[str, ...]]] = [
            ("Flash (All)", ("flash",)),
            ("Pro (2.5)", ("2.5 pro",)),
            ("Pro (3)", ("3 pro", "3.1 pro")),
            ("Claude (All)", ("claude", "gpt-oss")),
        ]

        availability_rows: list[ModelAvailability] = []
        for bucket_name, keywords in buckets:
            matches = [
                row
                for row in rows
                if any(keyword in row.identifier.lower() for keyword in keywords)
            ]
            if not matches:
                continue
            sample = matches[0]
            available_now = sample.pct_used < 99.0
            availability_rows.append(
                ModelAvailability(
                    name=f"Antigravity: {bucket_name}",
                    available_now=available_now,
                    available_when=None if available_now else sample.reset_at,
                )
            )
        return availability_rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        if rows and all(row.pct_used < 1.0 for row in rows):
            self.send_ntfy(
                "Antigravity Quota Fresh",
                "All Antigravity models are below 1% used.",
                tags="white_check_mark,rocket",
            )

    @classmethod
    def resolve_accounts(cls) -> Sequence[AntigravityAccount]:
        """Return one ``AntigravityAccount`` per credential email.

        Reads the V2 ``accounts.json`` index and skips accounts whose
        individual file has ``disabled: true``.
        """
        index = cast(V2AccountIndex, json.loads(ACCOUNTS_INDEX_PATH.read_text()))
        accounts: list[AntigravityAccount] = []
        for entry in index["accounts"]:
            acct_file = cast(
                V2AccountFile,
                json.loads((ACCOUNTS_DIR / f"{entry['id']}.json").read_text()),
            )
            if acct_file.get("disabled", False):
                continue
            accounts.append(cls(entry["email"]))
        return accounts


# Backward-compat alias
AntigravityProvider = AntigravityAccount
