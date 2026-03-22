"""Claude Code usage limits provider.

Aligned with OpenChamber implementation:
- Auth source: ~/.local/share/opencode/auth.json
- API: https://api.anthropic.com/api/oauth/usage
- Beta header: oauth-2025-04-20
- Token refresh: Automatic via `claude` CLI on 401 error
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class ClaudeProvider(UsageProvider):
    """Claude Code usage checker (5-hour and 7-day OAuth-gated windows)."""

    slug = "claude"
    name = "Claude Code"
    state_dir = "claude_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"
    API_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
    BETA_HEADER = "oauth-2025-04-20"

    def __init__(self) -> None:
        super().__init__()
        self.auth_file = Path.home() / ".local" / "share" / "opencode" / "auth.json"

    def provider_name(self) -> str:
        return "Claude"

    def get_credentials(self) -> dict[str, Any]:
        """Load OAuth credentials from ~/.local/share/opencode/auth.json.

        Expected structure:
        {
          "anthropic": {
            "type": "oauth",
            "access": "<access_token>",
            "refresh": "<refresh_token>",
            "expires": <timestamp>
          }
        }
        """
        if not self.auth_file.exists():
            return {}
        try:
            data = json.loads(self.auth_file.read_text())
            # Check for anthropic or claude keys (OpenChamber aliases)
            for key in ["anthropic", "claude"]:
                if key in data:
                    entry = data[key]
                    if isinstance(entry, dict):
                        return entry
            return {}
        except (json.JSONDecodeError, OSError):
            return {}

    def fetch_raw(self) -> dict[str, Any]:
        """Fetch usage from the Claude OAuth API with automatic token refresh."""
        creds = self.get_credentials()
        if not creds:
            print("Error: Not logged in. Run 'claude login'", file=sys.stderr)
            sys.exit(1)

        access_token = creds.get("access") or creds.get("token")
        if not access_token:
            print("Error: No access token", file=sys.stderr)
            sys.exit(1)

        try:
            return self._fetch_usage(access_token)
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                # Token expired - trigger automatic refresh via Claude CLI
                print("Warning: Token expired. Refreshing via Claude CLI...", file=sys.stderr)
                self._refresh_token_via_cli()
                # Reload credentials after refresh
                creds = self.get_credentials()
                access_token = creds.get("access") or creds.get("token")
                if not access_token:
                    print("Error: No access token after refresh", file=sys.stderr)
                    sys.exit(1)
                return self._fetch_usage(access_token)
            raise

    def _refresh_token_via_cli(self) -> None:
        """Trigger token refresh by running `claude` CLI briefly."""
        # Find claude CLI executable in PATH
        claude_path = shutil.which("claude")
        if claude_path is None:
            # CLI not installed, user needs to run `claude login` manually
            return

        # Use contextlib.suppress for cleaner exception handling (SIM105)
        with contextlib.suppress(
            subprocess.TimeoutExpired,
            FileNotFoundError,
            PermissionError,
            OSError,
        ):
            # Run claude CLI with a trivial command to trigger auth refresh
            subprocess.run(
                [claude_path, "--help"],
                capture_output=True,
                timeout=10,
                check=False,  # Don't fail if command fails
            )

    def _fetch_usage(self, token: str) -> dict[str, Any]:
        """Fetch usage data from Claude OAuth API."""
        resp = requests.get(
            self.API_ENDPOINT,
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": self.BETA_HEADER,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    def to_rows(self, raw: Any) -> list[UsageRow]:
        """Convert Claude API response to usage rows.

        Response structure:
        {
          "five_hour": {"utilization": 0.45, "resets_at": "2026-03-19T17:00:00Z"},
          "seven_day": {"utilization": 0.60, "resets_at": "2026-03-26T00:00:00Z"},
          "seven_day_sonnet": {...},
          "seven_day_opus": {...}
        }
        """
        rows: list[UsageRow] = []

        five_hour = raw.get("five_hour", {})
        if five_hour:
            rows.append(
                UsageRow(
                    identifier="Claude (5h)",
                    pct_used=float(five_hour.get("utilization", 0.0)) * 100,
                    reset_at=_parse_dt(five_hour.get("resets_at")),
                )
            )

        seven_day = raw.get("seven_day", {})
        if seven_day:
            rows.append(
                UsageRow(
                    identifier="Claude (7d)",
                    pct_used=float(seven_day.get("utilization", 0.0)) * 100,
                    reset_at=_parse_dt(seven_day.get("resets_at")),
                )
            )

        seven_day_sonnet = raw.get("seven_day_sonnet", {})
        if seven_day_sonnet:
            rows.append(
                UsageRow(
                    identifier="Claude (7d-sonnet)",
                    pct_used=float(seven_day_sonnet.get("utilization", 0.0)) * 100,
                    reset_at=_parse_dt(seven_day_sonnet.get("resets_at")),
                )
            )

        seven_day_opus = raw.get("seven_day_opus", {})
        if seven_day_opus:
            rows.append(
                UsageRow(
                    identifier="Claude (7d-opus)",
                    pct_used=float(seven_day_opus.get("utilization", 0.0)) * 100,
                    reset_at=_parse_dt(seven_day_opus.get("resets_at")),
                )
            )

        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Anchor when any window has never started and none are exhausted."""
        if any(r.is_exhausted for r in rows):
            return False
        return any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Fire when the 5h window is fresh and the 7d window isn't exhausted."""
        if self.should_anchor(rows):
            self.send_ntfy(
                "Claude Window Open",
                "Claude Code 5h window open!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str]:
        return ["claude", "--setting-sources", "", "Say hello and do nothing else"]


def _parse_dt(ts: str | None) -> datetime | None:
    """Parse ISO 8601 timestamp to datetime."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, TypeError):
        return None
