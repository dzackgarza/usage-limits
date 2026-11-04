"""Claude Code usage limits provider."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from typing import TypedDict, cast

import requests

from usage_limits.base import ProviderAccount
from usage_limits.auth.claude import claude_oauth_flow
from usage_limits.auth.store import CredentialStore, StoredCredential
from usage_limits.config import settings
from usage_limits.contracts import SavedResets
from usage_limits.table import UsageRow

# Claude Code's grant inventory requires its client surface on the OAuth usage call.
# https://github.com/KarpelesLab/teamclaude/blob/master/docs/accounts.md#claude-banked-usage-limit-resets
CLAUDE_USAGE_USER_AGENT = "claude-cli/2.1.318 (external, cli)"


class ClaudeLimitScope(TypedDict):
    model: dict[str, str | None]
    surface: str | None


class ClaudeLimitEntry(TypedDict):
    kind: str
    group: str
    percent: int
    severity: str
    resets_at: str | None
    scope: ClaudeLimitScope | None
    is_active: bool


class ClaudeSpendLimitWindow(TypedDict):
    utilization: float
    resets_at: str | None
    limit_dollars: float | int | None
    used_dollars: float | int | None
    remaining_dollars: float | int | None
    locked_reason: str | None


class ClaudeResetGrant(TypedDict):
    resets_left: int
    starts_at: str
    ends_at: str
    paused: bool
    usable_now: bool


class ClaudeResetInventory(TypedDict):
    eligible: bool
    ineligible_reason: str | None
    grants: list[ClaudeResetGrant]


class ClaudeUsageResponse(TypedDict):
    limits: list[ClaudeLimitEntry]
    iguana_necktie: ClaudeSpendLimitWindow | None
    cedar_ember: ClaudeResetInventory | None


class ClaudeProvider(ProviderAccount):
    """Claude Code usage checker via OAuth-gated limits API."""

    slug = "claude"
    name = "Claude Code"
    state_dir = "claude_usage"
    cache_ttl_seconds = 300  # default; override in config.ntfy.cache_ttl_seconds

    def __init__(self) -> None:
        super().__init__()
        self.store = CredentialStore()

    def provider_name(self) -> str:
        return "Claude"

    def get_credentials(self) -> StoredCredential:
        return self.store.get("claude", self.account_id)

    def _get_claude_bin(self) -> str:
        """Find the claude executable."""
        return shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")

    def _refresh(self, old_token: str) -> str:
        with self.store.lock("claude", self.account_id):
            credential = self.get_credentials()
            if credential["access_token"] != old_token:
                return credential["access_token"]
            refresh_token = credential["refresh_token"]
            assert refresh_token is not None
            result = claude_oauth_flow().refresh(refresh_token)
            credential["access_token"] = result["access_token"]
            credential["expires_at"] = result["expires_at"]
            if result["new_refresh_token"] is not None:
                credential["refresh_token"] = result["new_refresh_token"]
            self.store.save("claude", self.account_id, credential)
            return credential["access_token"]

    def fetch_raw(self) -> ClaudeUsageResponse:
        def _call(access_token: str) -> requests.Response:
            return requests.get(
                settings.claude.api_url,
                params={"cedar_ember": "1"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "anthropic-beta": settings.claude.beta_header,
                    "User-Agent": CLAUDE_USAGE_USER_AGENT,
                },
                timeout=30,
            )

        creds = self.get_credentials()
        access_token = creds["access_token"]
        expires_at = creds["expires_at"]
        assert expires_at is not None
        if datetime.fromisoformat(expires_at) <= datetime.now(UTC):
            access_token = self._refresh(access_token)
        resp = _call(access_token)
        if resp.status_code == 401:
            resp = _call(self._refresh(access_token))
        resp.raise_for_status()
        return cast(ClaudeUsageResponse, resp.json())

    def saved_resets(self, raw: ClaudeUsageResponse, *, at: datetime) -> SavedResets:
        block = raw["cedar_ember"]
        assert block is not None, "Claude usage response omitted reset inventory"
        if not block["eligible"]:
            reason = block["ineligible_reason"]
            if reason != "no_grant":
                raise ValueError(f"Claude reset inventory unavailable: {reason}")
            assert not block["grants"]
            return SavedResets(available_count=0, applicable_now_count=0)

        active = [
            grant
            for grant in block["grants"]
            if not grant["paused"]
            and datetime.fromisoformat(grant["starts_at"])
            <= at
            < datetime.fromisoformat(grant["ends_at"])
        ]
        return SavedResets(
            available_count=sum(grant["resets_left"] for grant in active),
            applicable_now_count=sum(
                grant["resets_left"] for grant in active if grant["usable_now"]
            ),
        )

    def to_rows(self, raw: ClaudeUsageResponse) -> list[UsageRow]:
        limits = raw["limits"]
        rows: list[UsageRow] = []
        for entry in limits:
            label = _limit_label(entry)
            rows.append(
                UsageRow(
                    identifier=label,
                    pct_used=entry["percent"],
                    reset_at=_parse_dt(entry["resets_at"]),
                )
            )

        spend_limit = raw["iguana_necktie"]
        if spend_limit is not None:
            limit_dollars = spend_limit["limit_dollars"]
            if limit_dollars is not None:
                label = f"Claude (API Spend ${int(limit_dollars)})"
            else:
                label = "Claude (API Spend)"
            rows.append(
                UsageRow(
                    identifier=label,
                    pct_used=round(spend_limit["utilization"]),
                    reset_at=_parse_dt(spend_limit["resets_at"]),
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
                "Claude Window Open",
                "Claude Code 5h window open!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str]:
        claude_bin = self._get_claude_bin()
        return [
            claude_bin,
            "--safe-mode",
            "--tools",
            "",
            "--no-session-persistence",
            "--system-prompt",
            "You are a minimal token refresher. Reply only with 'ok'.",
            "-p",
            "ok",
        ]


def _limit_label(entry: ClaudeLimitEntry) -> str:
    """Build a human-readable label from a limits-array entry."""
    scope = entry["scope"]
    if scope is not None and scope["model"] is not None:
        model_name = scope["model"]["display_name"]
        if model_name is not None:
            return f"Claude ({model_name})"
    group = entry["group"]
    return f"Claude ({group})"


def _parse_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
