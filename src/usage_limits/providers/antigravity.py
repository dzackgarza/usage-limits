"""Antigravity usage limits provider."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from typing import TypedDict, cast

from usage_limits.base import UsageProvider
from usage_limits.table import ModelAvailability, UsageRow


class AntigravityModel(TypedDict):
    label: str
    modelId: str
    remainingPercentage: float | None
    isExhausted: bool
    resetTime: str | None


class AntigravityRaw(TypedDict):
    models: list[AntigravityModel]


class AntigravityProvider(UsageProvider):
    """Antigravity usage checker backed by the antigravity-usage CLI."""

    slug = "antigravity"
    name = "Antigravity"
    state_dir = "antigravity_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def provider_name(self) -> str:
        return "Antigravity"

    def fetch_raw(self) -> AntigravityRaw:
        result = subprocess.run(
            ["npx", "--yes", "antigravity-usage", "quota", "--all-models", "--refresh", "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return cast(AntigravityRaw, json.loads(result.stdout))

    def to_rows(self, raw: AntigravityRaw) -> list[UsageRow]:
        rows: list[UsageRow] = []
        for model in raw["models"]:
            label = model["label"]
            remaining_percentage = model["remainingPercentage"]
            is_exhausted = model["isExhausted"]
            if is_exhausted or remaining_percentage is None:
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
                    identifier=f"Antigravity: {label}",
                    pct_used=pct_used,
                    reset_at=reset_at,
                )
            )
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
