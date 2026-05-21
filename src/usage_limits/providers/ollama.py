"""Ollama usage limits provider."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

import requests
from bs4 import BeautifulSoup

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class OllamaRaw(TypedDict):
    html: str


class OllamaProvider(UsageProvider):
    """Ollama Cloud usage checker (session and weekly windows via HTML scrape)."""

    slug = "ollama"
    name = "Ollama Cloud"
    state_dir = "ollama_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

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
        cookie_str = self.get_session_cookie()
        cookies = self.parse_cookie_string(cookie_str)

        response = requests.get(
            "https://ollama.com/settings",
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
        html = raw["html"]
        soup = BeautifulSoup(html, "html.parser")
        rows: list[UsageRow] = []

        label_mapping = {
            "session usage": "5h",
            "weekly usage": "7d",
        }

        for label_text in ["Session usage", "Weekly usage"]:
            label_elem = soup.find(
                string=lambda x, lt=label_text: bool(x and lt.lower() in x.lower())
            )
            if not label_elem:
                continue

            flex_container = label_elem.find_parent(
                "div", class_=lambda x: x and "flex" in x and "justify-between" in x
            )
            if not flex_container:
                continue

            percentage_text = flex_container.find(string=re.compile(r".*%\s*used.*", re.I))
            assert percentage_text is not None
            text = str(percentage_text).strip()
            match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*used", text, re.I)
            assert match is not None
            percentage = float(match.group(1))

            wrapper = flex_container.find_parent("div")
            reset_elem = (
                wrapper.find("div", class_=re.compile(r".*local-time.*")) if wrapper else None
            )
            reset_at = _parse_reset_element(reset_elem)

            window_name = label_mapping[label_text.lower()]
            rows.append(
                UsageRow(
                    identifier=f"Ollama ({window_name})",
                    pct_used=percentage,
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


def _parse_reset_element(elem: Any) -> datetime | None:
    if elem is None:
        return None

    data_time = elem.get("data-time") if hasattr(elem, "get") else None
    if data_time:
        return datetime.fromisoformat(data_time.replace("Z", "+00:00"))

    text = elem.get_text(strip=True) if hasattr(elem, "get_text") else str(elem)
    return _parse_reset_text(text)


def _parse_reset_text(text: str) -> datetime | None:
    if not text:
        return None
    text_lower = text.lower().strip()
    match = re.search(r"resets in (\d+)\s*(second|minute|hour|day|week)s?", text_lower)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    now = datetime.now(UTC)
    deltas = {
        "second": timedelta(seconds=value),
        "minute": timedelta(minutes=value),
        "hour": timedelta(hours=value),
        "day": timedelta(days=value),
        "week": timedelta(weeks=value),
    }
    return now + deltas[unit]
