"""Antigravity usage limits provider."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any, cast

from usage_limits.base import UsageProvider
from usage_limits.table import ModelAvailability, UsageRow


class AntigravityProvider(UsageProvider):
    """Antigravity usage checker backed by the antigravity-usage CLI."""

    slug = "antigravity"
    name = "Antigravity"
    state_dir = "antigravity_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def provider_name(self) -> str:
        return "Antigravity"

    def fetch_raw(self) -> dict[str, Any]:
        """Run the antigravity-usage CLI and parse its JSON response."""
        command = ["antigravity-usage", "quota", "--all-models", "--refresh", "--json"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            print(
                "Error: antigravity-usage not found. Install it before collecting quotas.",
                file=sys.stderr,
            )
            sys.exit(1)
        except subprocess.TimeoutExpired:
            print("Error: antigravity-usage timed out.", file=sys.stderr)
            sys.exit(1)

        if result.returncode != 0:
            stderr = result.stderr.strip().lower()
            if "not logged in" in stderr:
                print("Error: Not logged in. Run 'antigravity-usage login'.", file=sys.stderr)
            else:
                print(result.stderr.strip() or "Error: antigravity-usage failed.", file=sys.stderr)
            sys.exit(1)

        try:
            return cast(dict[str, Any], json.loads(result.stdout))
        except json.JSONDecodeError as error:
            print(f"Error: Invalid antigravity-usage JSON: {error}", file=sys.stderr)
            sys.exit(1)

    def to_rows(self, raw: Any) -> list[UsageRow]:
        """Convert per-model quota data into normalized rows."""
        rows: list[UsageRow] = []
        for model in raw.get("models", []):
            label = model.get("label", model.get("modelId", "unknown"))
            remaining_percentage = model.get("remainingPercentage")
            is_exhausted = model.get("isExhausted", False)
            if is_exhausted or remaining_percentage is None:
                pct_used = 100.0
            else:
                pct_used = (1.0 - remaining_percentage) * 100.0

            reset_at = None
            reset_time = model.get("resetTime")
            if reset_time:
                try:
                    reset_at = datetime.fromisoformat(reset_time.replace("Z", "+00:00")).astimezone(
                        UTC
                    )
                except ValueError:
                    reset_at = None

            rows.append(
                UsageRow(
                    identifier=f"Antigravity: {label}",
                    pct_used=pct_used,
                    reset_at=reset_at,
                )
            )
        return rows

    def availability(self, rows: list[UsageRow]) -> list[ModelAvailability]:
        """Group model-level quotas into the Antigravity availability buckets."""
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
        """Anchoring is handled by the external antigravity tooling."""
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Notify when all tracked Antigravity models are effectively fresh."""
        if rows and all(row.pct_used < 1.0 for row in rows):
            self.send_ntfy(
                "Antigravity Quota Fresh",
                "All Antigravity models are below 1% used.",
                tags="white_check_mark,rocket",
            )
