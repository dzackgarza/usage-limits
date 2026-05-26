"""OpenCode Go / Zen usage limits providers.

* OpenCodeGoProvider — fetches /workspace/{id}/go (the free tier)
* OpenCodeZenProvider — pings the free inference endpoint; a real response
  means the service is available (100%). No auth required.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TypedDict

import requests
from bs4 import BeautifulSoup

from usage_limits.base import ProviderAccount
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


class OpenCodeGoProvider(ProviderAccount):
    """OpenCode Go (free tier) usage checker via console cookie scraping."""

    slug = "opencode-go"
    name = "OpenCode Go"
    state_dir = "opencode_go"

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
        from usage_limits.config import settings as _cfg

        response = requests.get(
            _cfg.opencode.auth_url,
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


class OpenCodeZenProvider(ProviderAccount):
    """OpenCode Zen health check.

    Pings the free inference endpoint. A real response means the service
    is available — show 100%. Any error (timeout, 5xx, 4xx) propagates.
    No auth required.
    """

    slug = "opencode-zen"
    name = "OpenCode Zen"
    state_dir = "opencode_zen"

    # Defaults — override via config
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
        return [
            UsageRow(
                identifier="OpenCode Zen",
                pct_used=0.0 if raw["available"] else 100.0,
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
