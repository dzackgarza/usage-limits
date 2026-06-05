"""Ollama usage limits provider."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

import requests
from bs4 import BeautifulSoup

from usage_limits.base import ProviderAccount
from usage_limits.table import UsageRow


class OllamaRaw(TypedDict):
    html: str


class OllamaProvider(ProviderAccount):
    """Ollama Cloud usage checker (session and weekly windows via HTML scrape)."""

    slug = "ollama"
    name = "Ollama Cloud"
    state_dir = "ollama_usage"

    def __init__(self) -> None:
        super().__init__()

    def provider_name(self) -> str:
        return "Ollama"

    def _chrome_cookies(self) -> str:
        from browser_cookie3 import chromium

        cookies = list(chromium(domain_name="ollama.com"))
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

    def fetch_raw(self) -> OllamaRaw:
        from usage_limits.config import settings as _cfg

        cookie_str = self.get_session_cookie()
        cookies = self.parse_cookie_string(cookie_str)

        response = requests.get(
            _cfg.ollama.settings_url,
            cookies=cookies,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=30,
            allow_redirects=False,
        )
        response.raise_for_status()
        return {"html": response.text}

    def to_rows(self, raw: OllamaRaw) -> list[UsageRow]:
        soup = BeautifulSoup(raw["html"], "html.parser")
        rows: list[UsageRow] = []

        for track in soup.find_all("div", attrs={"aria-label": True}):
            aria = str(track["aria-label"])
            if not aria.startswith(("Session usage ", "Weekly usage ")):
                continue

            parts = aria.split()
            name = parts[0]
            percentage = float(parts[2].rstrip("%"))

            meter_div = track.parent
            assert meter_div is not None
            wrapper = meter_div.parent
            assert wrapper is not None
            reset_div = wrapper.find("div", attrs={"data-time": True})
            reset_at: datetime | None = None
            if reset_div is not None:
                data_time = str(reset_div["data-time"])
                reset_at = datetime.fromisoformat(data_time.replace("Z", "+00:00"))

            window = "5h" if name.lower() == "session" else "7d"
            rows.append(
                UsageRow(
                    identifier=f"Ollama ({window})",
                    pct_used=round(percentage),
                    reset_at=reset_at,
                )
            )

        return rows

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        five_hour = next((r for r in rows if "5h" in r.identifier), None)
        if not five_hour or five_hour.is_exhausted:
            return False
        return five_hour.reset_at is None or any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
        for row in (r for r in rows if "5h" in r.identifier):
            if row.pct_used < 50:
                self.send_ntfy(
                    "Ollama Window Open",
                    "Ollama Cloud 5h window open!\n\nFresh session available for work.",
                    tags="white_check_mark,rocket",
                )
                return

    def anchor_command(self) -> list[str]:
        return ["ollama", "run", "glm-4.6:cloud", "hi"]
