"""Provider for Google Cloud Code / Antigravity usage metrics.

Reads OAuth refresh tokens from the credential store, then queries the enforced
*individual* quota via ``v1internal:retrieveUserQuotaSummary``.

Why this endpoint and not ``fetchAvailableModels``:
``fetchAvailableModels`` reports a per-model ``remainingPercentage`` that does
*not* reflect the enforced individual quota — it returns ``1`` (100% available)
even when the account is fully rate-limited, so the dashboard would show "100%
available" while the CLI returns "Individual quota reached".
``retrieveUserQuotaSummary`` is the authoritative source the Antigravity CLI
itself uses: it exposes the real quota *pools* with their reset times and
exhaustion descriptions.

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

    def fetch_raw(self) -> AntigravityRaw:
        token = self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "antigravity",
        }
        resp = requests.post(
            f"{self._base_url()}/v1internal:retrieveUserQuotaSummary",
            headers=headers,
            json={},
        )
        resp.raise_for_status()
        return cast(AntigravityRaw, resp.json())

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
        for group in raw.get("groups", []):
            buckets = group.get("buckets", [])
            group_name = group.get("displayName", "")
            # Within a group, a disabled window is superseded by the binding
            # (most-restrictive active) window — render it with that limit/reset.
            active = [b for b in buckets if not b.get("disabled")]
            binding = (
                min(active, key=lambda b: b.get("remainingFraction", 0.0)) if active else None
            )
            for bucket in buckets:
                source = binding if (bucket.get("disabled") and binding is not None) else bucket
                remaining = source.get("remainingFraction")
                pct_used = 100.0 if remaining is None else (1.0 - remaining) * 100.0
                reset_at = self._parse_reset(source.get("resetTime"))

                window = bucket.get("window")
                if window:
                    identifier = f"{group_name} ({WINDOW_LABELS.get(window, window)})"
                else:
                    identifier = bucket.get("displayName") or bucket.get("bucketId", "")

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
