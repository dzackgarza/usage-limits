"""OpenCode Go / Zen usage limits providers.

* OpenCodeGoProvider — fetches /workspace/{id}/go (the free tier)
* OpenCodeZenProvider — probes a free model via the Zen API to determine
  availability.  200 → 0% (available), 429 → 100% (quota exhausted),
  any other status crashes with the raw traceback.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TypedDict

import requests
from bs4 import BeautifulSoup

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class OpenCodeRaw(TypedDict):
    html: str


class OpenCodeZenRaw(TypedDict):
    available: bool


WINDOW_MAP: dict[str, str] = {
    "Rolling Usage": "5h",
    "Weekly Usage": "7d",
    "Monthly Usage": "30d",
}


class OpenCodeGoProvider(UsageProvider):
    """OpenCode Go (free tier) usage checker via console cookie scraping."""

    slug = "opencode-go"
    name = "OpenCode Go"
    state_dir = "opencode_go"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self) -> None:
        super().__init__()

    def provider_name(self) -> str:
        return "OpenCode Go"

    def _chrome_cookies(self) -> str:
        from browser_cookie3 import chromium

        cookies = list(chromium(domain_name="opencode.ai"))
        return "; ".join(f"{c.name}={c.value}" for c in cookies)

    def get_session_cookie(self) -> str:
        return self._chrome_cookies()

    def parse_cookie_string(self, cookie_str: str) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                key, value = part.split("=", 1)
                cookies[key.strip()] = value.strip()
        return cookies

    def _discover_workspace_id(self, cookies: dict[str, str]) -> str:
        """Follow /auth redirect to discover the workspace ID."""
        response = requests.get(
            "https://opencode.ai/auth",
            cookies=cookies,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=30,
            allow_redirects=False,
        )
        location = response.headers.get("location", "")
        match = re.search(r"/workspace/(wrk_[A-Za-z0-9]+)", location)
        assert match is not None, f"Could not discover workspace ID from redirect: {location}"
        return match.group(1)

    def fetch_raw(self) -> OpenCodeRaw:
        cookie_str = self.get_session_cookie()
        cookies = self.parse_cookie_string(cookie_str)
        workspace_id = self._discover_workspace_id(cookies)

        response = requests.get(
            f"https://opencode.ai/workspace/{workspace_id}/go",
            cookies=cookies,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=30,
        )
        response.raise_for_status()
        return {"html": response.text}

    def to_rows(self, raw: OpenCodeRaw) -> list[UsageRow]:
        soup = BeautifulSoup(raw["html"], "html.parser")
        rows: list[UsageRow] = []

        for item in soup.find_all(attrs={"data-slot": "usage-item"}):
            label_elem = item.find(attrs={"data-slot": "usage-label"})
            value_elem = item.find(attrs={"data-slot": "usage-value"})
            reset_elem = item.find(attrs={"data-slot": "reset-time"})

            if not label_elem or not value_elem:
                continue

            label = label_elem.get_text(strip=True)
            short_label = WINDOW_MAP.get(label)
            if not short_label:
                continue

            value_text = value_elem.get_text(strip=True)
            match = re.search(r"(\d+(?:\.\d+)?)\s*%", value_text)
            assert match is not None, f"Could not parse usage value: {value_text!r}"
            pct = float(match.group(1))

            reset_at = _parse_reset_text(reset_elem.get_text(strip=True) if reset_elem else "")

            rows.append(
                UsageRow(
                    identifier=f"OpenCode Go ({short_label})",
                    pct_used=pct,
                    reset_at=reset_at,
                )
            )

        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        pass


class OpenCodeZenProvider(UsageProvider):
    """OpenCode Zen availability checker.

    Probes a free model via the open Zen inference endpoint (no auth required).
    429 → unavailable (100% used); 200 → available (0% used).
    Any other status or error is a hard crash — no masking.
    """

    slug = "opencode-zen"
    name = "OpenCode Zen"
    state_dir = "opencode_zen"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    API_BASE = "https://opencode.ai/zen/v1"
    PROBE_MODEL = "deepseek-v4-flash-free"

    def __init__(self) -> None:
        super().__init__()

    def provider_name(self) -> str:
        return "OpenCode Zen"

    def fetch_raw(self) -> OpenCodeZenRaw:
        resp = requests.post(
            f"{self.API_BASE}/chat/completions",
            headers={"Content-Type": "application/json"},
            json={
                "model": self.PROBE_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            },
            timeout=30,
        )
        if resp.status_code == 429:
            return {"available": False}
        resp.raise_for_status()
        return {"available": True}

    def to_rows(self, raw: OpenCodeZenRaw) -> list[UsageRow]:
        pct = 0.0 if raw["available"] else 100.0
        return [
            UsageRow(
                identifier="OpenCode Zen",
                pct_used=pct,
                reset_at=None,
            )
        ]

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        pass


# Backward-compat alias
OpenCodeProvider = OpenCodeGoProvider


def _parse_reset_text(text: str) -> datetime | None:
    text = text.strip().lower()
    match = re.search(
        r"resets in\s*"
        r"(?:(\d+)\s*d(?:ays?)?\s*)?"
        r"(?:(\d+)\s*h(?:ours?|rs?)?\s*)?"
        r"(?:(\d+)\s*m(?:inutes?|ins?)?\s*)?",
        text,
    )
    if not match:
        return None

    days = int(match.group(1)) if match.group(1) else 0
    hours = int(match.group(2)) if match.group(2) else 0
    minutes = int(match.group(3)) if match.group(3) else 0

    total_seconds = days * 86400 + hours * 3600 + minutes * 60
    if total_seconds == 0:
        return None

    return datetime.now(UTC) + timedelta(seconds=total_seconds)
