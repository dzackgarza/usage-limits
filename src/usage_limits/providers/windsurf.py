"""Windsurf usage limits provider."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class WindsurfCredentials(TypedDict):
    session_token: str


class WindsurfPlanStatusResponse(TypedDict):
    planStatus: WindsurfPlanStatus


class WindsurfPlanStatus(TypedDict):
    planInfo: WindsurfPlanInfo
    dailyQuotaRemainingPercent: int
    weeklyQuotaRemainingPercent: int
    dailyQuotaResetAtUnix: int
    weeklyQuotaResetAtUnix: int


class WindsurfPlanInfo(TypedDict):
    planName: str
    planEnd: WindsurfPlanEnd


class WindsurfPlanEnd(TypedDict):
    seconds: int


class WindsurfProvider(UsageProvider):
    """Windsurf usage checker (daily and weekly quotas)."""

    slug = "windsurf"
    name = "Windsurf"
    state_dir = "windsurf_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self) -> None:
        super().__init__()
        self.config_path = (
            Path.home()
            / ".config"
            / "Windsurf"
            / "User"
            / "globalStorage"
            / "storage.json"
        )

    def provider_name(self) -> str:
        return "Windsurf"

    def get_credentials(self) -> WindsurfCredentials:
        # Try to read from Windsurf config
        if self.config_path.exists():
            # This is a placeholder - actual implementation would need to find
            # where Windsurf stores the session token
            raise FileNotFoundError("Windsurf session token not found in config")

        # Fallback: user must provide credentials
        raise FileNotFoundError(
            "No Windsurf credentials found. Please configure session token."
        )

    def fetch_raw(self) -> WindsurfPlanStatusResponse:
        creds = self.get_credentials()

        # Encode session token as protobuf (simplified - field 1 string)
        session_token_bytes = creds["session_token"].encode("utf-8")
        body = bytes([0x0A, len(session_token_bytes)]) + session_token_bytes
        body += bytes([0x10, 0x01])  # field 2, value 1

        url = "https://windsurf.com/_backend/exa.seat_management_pb.SeatManagementService/GetPlanStatus"
        resp = requests.post(
            url,
            data=body,
            headers={
                "Content-Type": "application/proto",
                "Accept": "*/*",
                "Connect-Protocol-Version": "1",
                "X-Auth-Token": creds["session_token"],
                "Origin": "https://windsurf.com",
                "Referer": "https://windsurf.com/",
                "User-Agent": "usage-limits",
            },
            timeout=30,
        )
        resp.raise_for_status()

        # Parse protobuf response (simplified)
        # For now, return the raw bytes - full protobuf parsing would be needed
        # This is a placeholder for the actual implementation
        raise NotImplementedError("Protobuf parsing not yet implemented")

    def to_rows(self, raw: WindsurfUserStatusResponse) -> list[UsageRow]:
        plan_status = raw["userStatus"]["planStatus"]
        plan_info = plan_status["planInfo"]

        rows: list[UsageRow] = []

        # Prompt credits
        available_prompt = plan_status["availablePromptCredits"]
        used_prompt = plan_status["usedPromptCredits"]
        if available_prompt > 0:
            pct_used = used_prompt / available_prompt * 100
            reset_at = None
            if "planEnd" in plan_info:
                reset_at = __import__("datetime").datetime.fromtimestamp(
                    plan_info["planEnd"]["seconds"],
                    tz=__import__("datetime").timezone.utc,
                )

            rows.append(
                UsageRow(
                    identifier=f"Windsurf ({plan_info['planName']} - Prompt)",
                    pct_used=pct_used,
                    reset_at=reset_at,
                )
            )

        # Flow credits
        available_flow = plan_status["availableFlowCredits"]
        used_flow = plan_status["usedFlowCredits"]
        if available_flow > 0:
            pct_used = used_flow / available_flow * 100
            reset_at = None
            if "planEnd" in plan_info:
                reset_at = __import__("datetime").datetime.fromtimestamp(
                    plan_info["planEnd"]["seconds"],
                    tz=__import__("datetime").timezone.utc,
                )

            rows.append(
                UsageRow(
                    identifier=f"Windsurf ({plan_info['planName']} - Flow)",
                    pct_used=pct_used,
                    reset_at=reset_at,
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
                "Windsurf Window Open",
                "Windsurf credits available!\\n\\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str] | None:
        return None
