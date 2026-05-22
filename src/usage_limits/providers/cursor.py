"""Cursor usage limits provider."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TypedDict, cast

import requests

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class CursorUsageSummary(TypedDict):
    membershipType: str
    gpt4: CursorModelUsage
    gpt35: CursorModelUsage
    codex: CursorModelUsage
    o1: CursorModelUsage
    sonnet: CursorModelUsage
    o3Pro: CursorModelUsage
    gemini: CursorModelUsage
    geminiPro: CursorModelUsage
    aurora: CursorModelUsage
    cursorPro: CursorModelUsage
    cursorPremPlus: CursorModelUsage
    cursorPremUlt: CursorModelUsage


class CursorModelUsage(TypedDict):
    numRequests: int
    maxRequestUsage: int | str


class CursorUsageResponse(TypedDict):
    membershipType: str
    gpt4: CursorModelUsage
    gpt35: CursorModelUsage
    codex: CursorModelUsage
    o1: CursorModelUsage
    sonnet: CursorModelUsage
    o3Pro: CursorModelUsage
    gemini: CursorModelUsage
    geminiPro: CursorModelUsage
    aurora: CursorModelUsage
    cursorPro: CursorModelUsage
    cursorPremPlus: CursorModelUsage
    cursorPremUlt: CursorModelUsage


class CursorProvider(UsageProvider):
    """Cursor usage checker (per-model request quotas)."""

    slug = "cursor"
    name = "Cursor"
    state_dir = "cursor_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    USAGE_URL = "https://cursor.com/api/usage-summary"

    def __init__(self) -> None:
        super().__init__()
        self.state_db = (
            Path.home()
            / ".config"
            / "Cursor"
            / "User"
            / "globalStorage"
            / "state.vscdb"
        )

    def provider_name(self) -> str:
        return "Cursor"

    def get_access_token(self) -> str:
        conn = sqlite3.connect(self.state_db)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT value FROM ItemTable WHERE key = 'cursorAuth/accessToken'"
        )
        row = cursor.fetchone()
        conn.close()
        return row[0]

    def fetch_raw(self) -> CursorUsageResponse:
        access_token = self.get_access_token()

        # Build WorkosCursorSessionToken cookie
        # accessToken is a JWT, extract sub to get user_id
        jwt_payload = access_token.split(".")[1]
        import base64

        # Add padding
        jwt_payload += "=" * (4 - len(jwt_payload) % 4)
        decoded = json.loads(base64.b64decode(jwt_payload))
        sub = decoded.get("sub", "")
        user_id = sub.split("|")[-1] if "|" in sub else sub

        cookie = f"WorkosCursorSessionToken={user_id}%3A%3A{access_token}"

        resp = requests.get(
            self.USAGE_URL,
            headers={
                "Accept": "application/json",
                "Cookie": cookie,
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return cast(CursorUsageResponse, resp.json())

    def to_rows(self, raw: CursorUsageResponse) -> list[UsageRow]:
        membership = raw["membershipType"]
        rows: list[UsageRow] = []

        model_keys = [
            "gpt4",
            "gpt35",
            "codex",
            "o1",
            "sonnet",
            "o3Pro",
            "gemini",
            "geminiPro",
            "aurora",
            "cursorPro",
            "cursorPremPlus",
            "cursorPremUlt",
        ]

        for model_key in model_keys:
            if model_key not in raw:
                continue

            model_data = raw[model_key]
            num_requests = model_data["numRequests"]
            max_usage = model_data["maxRequestUsage"]

            if isinstance(max_usage, int) and max_usage > 0:
                pct_used = (num_requests / max_usage) * 100
                rows.append(
                    UsageRow(
                        identifier=f"Cursor ({membership} - {model_key})",
                        pct_used=pct_used,
                        reset_at=None,
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
                "Cursor Window Open",
                "Cursor credits available!\n\nFresh session available for work.",
                tags="white_check_mark,rocket",
            )

    def anchor_command(self) -> list[str] | None:
        return None
