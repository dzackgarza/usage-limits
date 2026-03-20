"""GitHub Copilot usage limits provider."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class CopilotProvider(UsageProvider):
    """GitHub Copilot usage checker (chat, completions, and premium windows)."""

    slug = "copilot"
    name = "GitHub Copilot"
    state_dir = "copilot_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self) -> None:
        super().__init__()
        self.auth_file = Path.home() / ".local" / "share" / "opencode" / "auth.json"

    def provider_name(self) -> str:
        return "GitHub Copilot"

    def get_credentials(self) -> dict[str, Any]:
        """Load auth credentials from ~/.local/share/opencode/auth.json."""
        if not self.auth_file.exists():
            return {}
        try:
            data = json.loads(self.auth_file.read_text())
            # Check for github-copilot or copilot keys
            for key in ["github-copilot", "copilot"]:
                if key in data:
                    entry = data[key]
                    if isinstance(entry, str):
                        return {"access_token": entry}
                    if isinstance(entry, dict):
                        return entry
            return {}
        except (json.JSONDecodeError, OSError):
            return {}

    def fetch_raw(self) -> dict[str, Any]:
        """Fetch usage from the GitHub Copilot internal API."""
        creds = self.get_credentials()
        if not creds:
            msg = (
                "Not logged in. Configure GitHub Copilot auth in ~/.local/share/opencode/auth.json"
            )
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)
        token = creds.get("access") or creds.get("access_token")
        if not token:
            print("Error: No access token", file=sys.stderr)
            sys.exit(1)

        try:
            resp = requests.get(
                "https://api.github.com/copilot_internal/user",
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/json",
                    "Editor-Version": "vscode/1.96.2",
                    "X-Github-Api-Version": "2025-04-01",
                },
                timeout=30,
            )
            if resp.status_code == 401:
                print(
                    "Error: Authentication failed. Please re-authenticate with GitHub Copilot",
                    file=sys.stderr,
                )
                sys.exit(1)
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except requests.RequestException as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    def to_rows(self, raw: Any) -> list[UsageRow]:
        quota_snapshots = raw.get("quota_snapshots", {})
        reset_date = raw.get("quota_reset_date")
        reset_at = _parse_dt(reset_date) if reset_date else None

        rows: list[UsageRow] = []

        # Chat quota
        chat = quota_snapshots.get("chat", {})
        if chat:
            entitlement = chat.get("entitlement")
            remaining = chat.get("remaining")
            pct_used = _calculate_percent(entitlement, remaining)
            rows.append(
                UsageRow(
                    identifier="Copilot Chat",
                    pct_used=pct_used,
                    reset_at=reset_at,
                )
            )

        # Completions quota
        completions = quota_snapshots.get("completions", {})
        if completions:
            entitlement = completions.get("entitlement")
            remaining = completions.get("remaining")
            pct_used = _calculate_percent(entitlement, remaining)
            rows.append(
                UsageRow(
                    identifier="Copilot Completions",
                    pct_used=pct_used,
                    reset_at=reset_at,
                )
            )

        # Premium interactions quota
        premium = quota_snapshots.get("premium_interactions", {})
        if premium:
            entitlement = premium.get("entitlement")
            remaining = premium.get("remaining")
            pct_used = _calculate_percent(entitlement, remaining)
            rows.append(
                UsageRow(
                    identifier="Copilot Premium",
                    pct_used=pct_used,
                    reset_at=reset_at,
                )
            )

        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Anchor when any window has never started and none are exhausted."""
        if any(r.is_exhausted for r in rows):
            return False
        return any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Fire when windows are fresh."""
        if self.should_anchor(rows):
            self.send_ntfy(
                "Copilot Window Open",
                "GitHub Copilot quota reset!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str]:
        return ["gh", "copilot", "chat", "Say hello and do nothing else"]


def _calculate_percent(entitlement: float | None, remaining: float | None) -> float:
    """Calculate percentage used from entitlement and remaining."""
    if entitlement is None or remaining is None or entitlement == 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 - (remaining / entitlement * 100.0)))


def _parse_dt(ts: str | None) -> datetime | None:
    """Parse ISO 8601 timestamp to datetime."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, TypeError):
        return None
