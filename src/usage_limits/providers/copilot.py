"""GitHub Copilot usage limit provider."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from typing import Any

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow

__all__ = ["CopilotProvider"]


class CopilotProvider(UsageProvider):
    """Provider for GitHub Copilot."""

    slug = "copilot"
    name = "GitHub Copilot"
    state_dir = "copilot"

    def fetch_raw(self) -> Any:
        """Fetch raw usage data from the GitHub CLI."""
        try:
            result = subprocess.run(
                ["gh", "api", "/user/copilot_billing"],
                capture_output=True,
                text=True,
                check=True,
            )
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
            return {}

    def to_rows(self, raw: Any) -> list[UsageRow]:
        """Convert provider data into uniform usage rows."""
        if not isinstance(raw, dict):
            return []

        # Default to 0 limit to indicate no premium requests data found
        premium_requests_used = raw.get("premium_requests_used", 0)
        premium_requests_limit = raw.get("premium_requests_limit", 0)

        if premium_requests_limit > 0:
            pct_used = (premium_requests_used / premium_requests_limit) * 100.0
        else:
            pct_used = 0.0

        now = datetime.now(UTC)

        # End of current calendar month UTC midnight
        if now.month == 12:
            next_month_year = now.year + 1
            next_month = 1
        else:
            next_month_year = now.year
            next_month = now.month + 1

        reset_at = datetime(next_month_year, next_month, 1, tzinfo=UTC)

        return [
            UsageRow(
                identifier="Copilot (monthly)",
                pct_used=pct_used,
                reset_at=reset_at,
            )
        ]

    def provider_name(self) -> str:
        """Return the short display label used in availability views."""
        return "Copilot"

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Return True when the provider should anchor an idle usage window."""
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Send any immediate notifications for freshly available capacity."""
        pass
