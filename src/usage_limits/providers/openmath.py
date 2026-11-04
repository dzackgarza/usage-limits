"""OpenMath usage limits provider."""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.table import UsageRow


class OpenMathWindow(TypedDict):
    limit_usd: float
    resets_at: str | None
    spent_usd: float
    window: str


class OpenMathUsageResponse(TypedDict):
    windows: list[OpenMathWindow]


class OpenMathOrg(TypedDict):
    id: str
    name: str


class OpenMathOrgsResponse(TypedDict):
    orgs: list[OpenMathOrg]


WINDOW_MAP: dict[str, str] = {
    "5h": "5h",
    "week": "7d",
}


class OpenMathProvider(ProviderAccount):
    """OpenMath usage checker via org_model_usage API."""

    slug = "openmath"
    name = "OpenMath"
    state_dir = "openmath_usage"

    def provider_name(self) -> str:
        return "OpenMath"

    def get_token(self) -> str:
        if "OPENMATH_SESSION_TOKEN" in os.environ:
            return os.environ["OPENMATH_SESSION_TOKEN"]
        if "OPENMATH_TOKEN" in os.environ:
            return os.environ["OPENMATH_TOKEN"]
        from usage_limits.auth.store import CredentialStore

        store = CredentialStore()
        return store.get("openmath", self.account_id)["access_token"]

    def fetch_team_id(self, token: str) -> str:
        from usage_limits.config import settings as _cfg

        resp = requests.post(
            _cfg.openmath.orgs_url,
            headers={"authorization": f"Bearer {token}"},
            json={},
            timeout=30,
        )
        resp.raise_for_status()
        data = cast(OpenMathOrgsResponse, resp.json())
        orgs = data["orgs"]
        assert len(orgs) > 0, "No teams found in OpenMath orgs response"
        if self.account_id != "default":
            for org in orgs:
                if org["id"] == self.account_id or org["name"] == self.account_id:
                    return org["id"]
        return orgs[0]["id"]

    def get_team_id(self, token: str) -> str:
        if "OPENMATH_TEAM_ID" in os.environ:
            return os.environ["OPENMATH_TEAM_ID"]
        return self.fetch_team_id(token)

    def fetch_raw(self) -> OpenMathUsageResponse:
        from usage_limits.config import settings as _cfg

        token = self.get_token()
        team_id = self.get_team_id(token)
        url = _cfg.openmath.api_url
        headers = {"authorization": f"Bearer {token}"}
        payload = {"team": team_id}
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        return cast(OpenMathUsageResponse, resp.json())

    def to_rows(self, raw: OpenMathUsageResponse) -> list[UsageRow]:
        windows = raw["windows"]
        rows: list[UsageRow] = []
        for win in windows:
            api_window = win["window"]
            target_window = WINDOW_MAP[api_window]
            limit = win["limit_usd"]
            spent = win["spent_usd"]
            if limit <= 0:
                pct_used = 100
            else:
                pct_used = round((spent / limit) * 100.0)

            reset_text = win["resets_at"]
            reset_at = (
                datetime.fromisoformat(reset_text.replace("Z", "+00:00")).astimezone(
                    UTC
                )
                if reset_text is not None
                else None
            )
            rows.append(
                UsageRow(
                    identifier=f"OpenMath ({target_window})",
                    pct_used=pct_used,
                    reset_at=reset_at,
                )
            )
        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        pass

    @classmethod
    def resolve_accounts(cls) -> Sequence[OpenMathProvider]:
        from usage_limits.auth.store import CredentialStore

        store = CredentialStore()
        accounts = store.list_accounts("openmath")
        if not accounts:
            return [cls()]
        return [cls(account_id=acc) for acc in accounts]
