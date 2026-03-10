"""Ollama usage limits provider."""

from __future__ import annotations

import os
import re
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup

from usage_limits.base import UsageProvider
from usage_limits.table import UsageRow


class OllamaProvider(UsageProvider):
    """Ollama Cloud usage checker (session and weekly windows via HTML scrape)."""

    slug = "ollama"
    name = "Ollama Cloud"
    state_dir = "ollama_usage"
    ntfy_topic = "usage-updates"
    ntfy_server = "http://localhost"

    def __init__(self) -> None:
        super().__init__()
        self.cookie = os.environ.get("OLLAMA_SESSION_COOKIE")

    def provider_name(self) -> str:
        return "Ollama"

    def get_session_cookie(self) -> str:
        """Get session cookie from environment."""
        if not self.cookie:
            print(
                "Error: OLLAMA_SESSION_COOKIE not set.\n"
                "Add it to ~/.envrc and run 'direnv allow' or export it manually.",
                file=sys.stderr,
            )
            sys.exit(1)
        return self.cookie

    def parse_cookie_string(self, cookie_str: str) -> dict[str, str]:
        """Parse a semicolon-separated cookie string into a dict."""
        cookies: dict[str, str] = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                key, value = part.split("=", 1)
                cookies[key.strip()] = value.strip()
        return cookies

    def fetch_raw(self) -> dict[str, Any]:
        """Fetch usage from the Ollama Cloud settings page."""
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

        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location", "unknown")
            print(
                f"Error: Session cookie expired. Got redirect to: {location}",
                file=sys.stderr,
            )
            sys.exit(1)

        if "signin" in response.text.lower() and "ollama.com" in response.text.lower():
            print(
                "Error: Session cookie expired or invalid. The response contains a login page.\n"
                "Get a fresh cookie from your browser's DevTools.",
                file=sys.stderr,
            )
            sys.exit(1)

        response.raise_for_status()
        return {"html": response.text}

    def to_rows(self, raw: Any) -> list[UsageRow]:
        """Parse the settings page HTML into UsageRow list."""
        html = raw.get("html", "")
        soup = BeautifulSoup(html, "html.parser")
        rows: list[UsageRow] = []

        # Map Ollama's labels to standard 5h/7d naming (matching Claude/Codex)
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

            percentage: float | None = None
            percentage_text = flex_container.find(string=re.compile(r".*%\s*used.*", re.I))
            if percentage_text:
                text = str(percentage_text).strip()
                match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*used", text, re.I)
                if match:
                    percentage = float(match.group(1))

            wrapper = flex_container.find_parent("div")
            reset_elem = None
            if wrapper:
                reset_elem = wrapper.find("div", class_=re.compile(r".*local-time.*"))
            reset_text = reset_elem.get_text(strip=True) if reset_elem else None
            reset_at = self._parse_reset_time(reset_text)

            window_name = label_mapping.get(label_text.lower(), label_text.split()[0])
            rows.append(
                UsageRow(
                    identifier=f"Ollama ({window_name})",
                    pct_used=percentage if percentage is not None else 0.0,
                    reset_at=reset_at,
                )
            )

        return rows

    def _parse_reset_time(self, text: str | None) -> datetime | None:
        """Parse reset time from text like 'Resets in 5 hours' or 'Resets in 1 day'."""
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

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Anchor when the 5h window has no reset_at and is not exhausted.

        | 5h          | 7d          | Anchor? |
        |-------------|-------------|---------|
        | no reset    | no reset    | Yes     |
        | no reset    | active      | Yes     |
        | no reset    | exhausted   | No      |
        | active      | no reset    | Yes     |
        | active      | active      | No      |
        | active      | exhausted   | No      |
        | exhausted   | any         | No      |
        """
        five_hour = next((r for r in rows if "5h" in r.identifier), None)
        if not five_hour or five_hour.is_exhausted:
            return False
        return five_hour.reset_at is None or any(r.reset_at is None for r in rows)

    def notify_always(self, rows: list[UsageRow]) -> None:
        """Fire when the 5h window is fresh (< 50% used)."""
        for row in (r for r in rows if "5h" in r.identifier):
            if row.pct_used < 50:
                self.send_ntfy(
                    "Ollama Window Open",
                    "Ollama Cloud 5h window open!\n\nFresh session available for work.",
                    tags="white_check_mark,rocket",
                )
                return

    def anchor_command(self) -> list[str]:
        """Anchor the 5h window by running a minimal cloud inference request."""
        return ["ollama", "run", "glm-4.6:cloud", "hi"]
