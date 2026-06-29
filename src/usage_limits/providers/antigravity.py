"""Provider for Google Cloud Code / Antigravity usage metrics.

Reads OAuth refresh tokens from the credential store, then follows the same
quota handshake as agy: ``v1internal:loadCodeAssist`` first, then
``v1internal:retrieveUserQuotaSummary`` with the returned project string.

Why the project-scoped summary request:
An empty ``retrieveUserQuotaSummary`` request returns the stale per-model
"everything available" shape for accounts whose real agy quota is exhausted.
The agy runtime cache for quota summary depends on ``loadCodeAssistResponse``;
passing ``{"project": cloudaicompanionProject}`` returns the enforced quota
pools that match agy's visible limit state.

``fetchAvailableModels`` is still part of agy's startup path, but it is a model
configuration/listing call. It does not by itself provide the enforced quota
summary rendered here.

Response shapes (both are ``groups[].buckets[]``):
  * Pooled plans: one group per model family ("Gemini Models", "Claude and GPT
    models"), each with a ``weekly`` and a ``5h`` bucket carrying a ``window``
    field. Models in a family share the pool.
  * Per-model plans: a single "All Models" group with one bucket per model
    (no ``window`` field; the bucket ``displayName`` is the model label).

A bucket marked ``disabled`` is not the active limiter for its group (another
window already blocks it); we render it with the binding bucket's limit and
reset so the row reflects when the family actually frees up.

The OAuth client ID and secret are hardcoded. These are public; the actual
secret is each account's refresh token.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.table import ModelAvailability, UsageRow

# Display label per quota window; absent on older per-model plans.
WINDOW_LABELS: dict[str, str] = {"weekly": "Weekly", "5h": "5h"}


class QuotaBucket(TypedDict, total=False):
    bucketId: str
    displayName: str
    window: str  # "weekly" | "5h"; absent on per-model plans
    resetTime: str
    description: str
    disabled: bool
    remainingFraction: float


class QuotaGroup(TypedDict, total=False):
    buckets: list[QuotaBucket]
    displayName: str
    description: str


class AntigravityRaw(TypedDict):
    groups: list[QuotaGroup]


class LoadCodeAssistResponse(TypedDict):
    cloudaicompanionProject: str


class LoadCodeAssistMetadata(TypedDict):
    ideType: str
    platform: str
    pluginType: str


class LoadCodeAssistRequest(TypedDict):
    metadata: LoadCodeAssistMetadata


class RetrieveUserQuotaSummaryRequest(TypedDict):
    project: str


class AntigravityAccount(ProviderAccount):
    """Antigravity usage checker for a single account.

    One instance per credential email. Use ``resolve_accounts()`` to
    discover all accounts from the credential store
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

    def _get_access_token(self) -> str:
        """Get a fresh access token for ``self.account_id``."""
        from usage_limits.auth.oauth import LocalhostBrowserFlow
        from usage_limits.auth.store import CredentialStore
        from usage_limits.config import settings as _cfg

        store = CredentialStore()
        cred = store.get("antigravity", self.account_id)

        refresh_token = cred.get("refresh_token")
        if not refresh_token:
            raise RuntimeError(f"No refresh token for account {self.account_id}")

        cfg = _cfg.antigravity
        flow = LocalhostBrowserFlow(
            client_id=cfg.client_id,
            client_secret=cfg.client_secret,
            scopes=[],
            auth_url="",
            token_url=cfg.oauth_token_endpoint,
            use_pkce=False,
        )

        result = flow.refresh(refresh_token)
        cred["access_token"] = result["access_token"]
        if result["expires_at"]:
            cred["expires_at"] = result["expires_at"]
        if result["new_refresh_token"] is not None:
            cred["refresh_token"] = result["new_refresh_token"]
        store.save("antigravity", self.account_id, cred)

        return result["access_token"]

    def _base_url(self) -> str:
        """Cloud Code host to query. Overridable by subclasses (e.g. the secret pool)."""
        from usage_limits.config import settings as _cfg

        return _cfg.antigravity.cloudcode_base_url

    def _request_headers(self) -> dict[str, str]:
        token = self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "antigravity",
        }

    @staticmethod
    def _load_code_assist_request() -> LoadCodeAssistRequest:
        return {
            "metadata": {
                "ideType": "ANTIGRAVITY",
                "platform": "PLATFORM_UNSPECIFIED",
                "pluginType": "GEMINI",
            }
        }

    def _load_code_assist(self, headers: dict[str, str]) -> LoadCodeAssistResponse:
        load_resp = requests.post(
            f"{self._base_url()}/v1internal:loadCodeAssist",
            headers=headers,
            json=self._load_code_assist_request(),
        )
        load_resp.raise_for_status()
        return cast(LoadCodeAssistResponse, load_resp.json())

    def _retrieve_user_quota_summary(
        self,
        headers: dict[str, str],
        summary_request: RetrieveUserQuotaSummaryRequest,
    ) -> AntigravityRaw:
        resp = requests.post(
            f"{self._base_url()}/v1internal:retrieveUserQuotaSummary",
            headers=headers,
            json=summary_request,
        )
        resp.raise_for_status()
        return cast(AntigravityRaw, resp.json())

    def fetch_raw(self) -> AntigravityRaw:
        headers = self._request_headers()
        load_raw = self._load_code_assist(headers)
        summary_request = self._quota_summary_request(load_raw)
        return self._retrieve_user_quota_summary(headers, summary_request)

    @staticmethod
    def _quota_summary_request(
        load_raw: LoadCodeAssistResponse,
    ) -> RetrieveUserQuotaSummaryRequest:
        return {"project": load_raw["cloudaicompanionProject"]}

    @staticmethod
    def _model_sort_key(identifier: str) -> tuple[int, str]:
        """Sort key: Gemini families first, then Claude/GPT, then anything else."""
        label = identifier.lower()
        if "gemini" in label:
            return 0, label
        if "claude" in label or "gpt" in label:
            return 1, label
        return 2, label

    @staticmethod
    def _parse_reset(reset_time: str | None) -> datetime | None:
        if not reset_time:
            return None
        return datetime.fromisoformat(reset_time.replace("Z", "+00:00")).astimezone(UTC)

    def to_rows(self, raw: AntigravityRaw) -> list[UsageRow]:
        rows: list[UsageRow] = []
        for group in raw["groups"]:
            buckets = group["buckets"]
            group_name = group["displayName"]
            # Within a group, a disabled window is superseded by the binding
            # (most-restrictive active) window — render it with that limit/reset.
            active = [b for b in buckets if not b.get("disabled")]
            binding = min(active, key=lambda b: b["remainingFraction"]) if active else None
            for bucket in buckets:
                source = binding if (bucket.get("disabled") and binding is not None) else bucket
                remaining = source["remainingFraction"]
                pct_used = (1.0 - remaining) * 100.0
                reset_at = self._parse_reset(source["resetTime"])

                window = bucket.get("window")
                if window:
                    identifier = f"{group_name} ({WINDOW_LABELS.get(window, window)})"
                else:
                    identifier = bucket["displayName"]

                rows.append(
                    UsageRow(identifier=identifier, pct_used=round(pct_used), reset_at=reset_at)
                )

        rows.sort(key=lambda r: self._model_sort_key(r.identifier))
        return rows

    def availability(self, rows: list[UsageRow]) -> list[ModelAvailability]:
        # Pooled plans share quota per family; per-model plans expose model rows.
        # Either way these keywords classify a row into one of two families.
        families: list[tuple[str, tuple[str, ...]]] = [
            ("Gemini", ("gemini",)),
            ("Claude/GPT", ("claude", "gpt")),
        ]

        availability_rows: list[ModelAvailability] = []
        for family_name, keywords in families:
            matches = [
                row
                for row in rows
                if any(keyword in row.identifier.lower() for keyword in keywords)
            ]
            if not matches:
                continue
            exhausted = [row for row in matches if row.pct_used >= 99]
            available_now = not exhausted
            available_when = (
                None
                if available_now
                else min(
                    (row.reset_at for row in exhausted if row.reset_at is not None),
                    default=None,
                )
            )
            availability_rows.append(
                ModelAvailability(
                    name=f"{self.name}: {family_name}",
                    available_now=available_now,
                    available_when=available_when,
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

        Reads from the CredentialStore.
        """
        from usage_limits.auth.store import CredentialStore

        store = CredentialStore()
        accounts = store.list_accounts("antigravity")
        return [cls(acct) for acct in accounts]
