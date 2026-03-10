"""Amp usage limits provider.

Amp replenishes continuously at a fixed $/hour rate up to a $10 cap.
There is no anchor concept — credits fill automatically.
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class AmpProvider(UsageProvider):
    """Amp usage checker.

    Credits replenish continuously at a fixed $/hour rate up to a $10 cap.
    Notifications fire immediately when full, or scheduled for the exact hour
    credits will reach $10.
    """

    slug = "amp"
    name = "Amp"
    state_dir = "amp_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def provider_name(self) -> str:
        return "Amp"

    def fetch_raw(self) -> dict[str, Any]:
        """Run `amp usage` and parse the text output."""
        result = subprocess.run(
            ["amp", "usage"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print("Error: Run 'amp login' first", file=sys.stderr)
            sys.exit(1)
        return _parse_amp_output(result.stdout)

    def to_rows(self, raw: Any) -> list[UsageRow]:
        """Single row: Amp credits, reset_at = when credits will be full (None if already full)."""
        remaining = raw.get("remaining", 0.0)
        total = raw.get("total", 10.0)
        rate = raw.get("rate_per_hour", 0.0)

        used = total - remaining
        pct_used = (used / total * 100) if total > 0 else 0.0

        topup_dt, hours_needed = _next_topup_time(remaining, total, rate)
        reset_at = None if hours_needed == 0 else topup_dt

        return [UsageRow(identifier="Amp", pct_used=pct_used, reset_at=reset_at)]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Amp credits replenish automatically — no anchoring needed."""
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Fire immediately when credits are full ($10.00 available)."""
        if rows and rows[0].reset_at is None:
            self.send_ntfy(
                "Amp Credits Full",
                "Amp credits full!\n\nOptimal time to run tasks.",
                tags="white_check_mark,rocket",
            )

    def _handle_notifications(self, rows: list[UsageRow]) -> None:
        """Schedule a notification for when credits will reach $10."""
        if not rows or rows[0].reset_at is None:
            return  # full: already handled by notify_always

        topup_time = rows[0].reset_at
        notif_id = f"amp-topup-{int(topup_time.timestamp())}"

        if self._notification_scheduled(notif_id):
            print("i  Top-up notification already scheduled")
            return

        time_to_topup = topup_time - datetime.now(UTC)
        hours = math.ceil(time_to_topup.total_seconds() / 3600)
        at_time = f"{hours} hour{'s' if hours != 1 else ''}"

        success, _ = self.send_ntfy(
            title="Amp Top-Up",
            message="Amp credits topped up!\n\nFull credits available.",
            tags=f"white_check_mark,clock,notif_id:{notif_id}",
            at=at_time,
        )
        if success:
            print(
                f"🔔 Notification scheduled for "
                f"{topup_time.astimezone().strftime('%Y-%m-%d %H:%M')}"
            )
        else:
            print("✗ Failed to schedule notification")


def _parse_amp_output(output: str) -> dict[str, float]:
    """Parse `amp usage` text output into structured dict."""
    match = re.search(
        r"Amp Free: \$(\d+\.?\d*)/\$(\d+\.?\d*) remaining \(replenishes \+\$(\d+\.?\d*)/hour\)",
        output,
    )
    if not match:
        return {}
    return {
        "remaining": float(match.group(1)),
        "total": float(match.group(2)),
        "rate_per_hour": float(match.group(3)),
    }


def _next_topup_time(remaining: float, total: float, rate: float) -> tuple[datetime, int]:
    """Calculate when credits will be full and how many hours that takes."""
    needed = total - remaining
    if needed <= 0 or rate <= 0:
        return datetime.now(UTC), 0
    hours_needed = math.ceil(needed / rate)
    now = datetime.now(UTC)
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    topup_time = next_hour + timedelta(hours=hours_needed - 1)
    return topup_time, hours_needed
