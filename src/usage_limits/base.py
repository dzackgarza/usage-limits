"""Abstract base class for all usage-limit providers."""

from __future__ import annotations

import json
import subprocess
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from usage_limits.contracts import ProviderSnapshot
from usage_limits.table import ModelAvailability, UsageRow, UsageTable

__all__ = ["UsageProvider"]


class UsageProvider(ABC):
    """Abstract base for all usage-limit providers."""

    slug: str
    name: str
    state_dir: str
    ntfy_topic: str = "usage-updates"
    ntfy_server: str = "http://localhost"

    def __init__(self) -> None:
        self._state_path = Path.home() / ".local" / "state" / self.state_dir
        self._state_path.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def fetch_raw(self) -> Any:
        """Fetch raw usage data from an external API or CLI."""

    @abstractmethod
    def to_rows(self, raw: Any) -> list[UsageRow]:
        """Convert provider data into uniform usage rows."""

    @abstractmethod
    def provider_name(self) -> str:
        """Return the short display label used in availability views."""

    @abstractmethod
    def should_anchor(self, rows: list[UsageRow]) -> bool:
        """Return True when the provider should anchor an idle usage window."""

    @abstractmethod
    def notify_always(self, rows: list[UsageRow]) -> None:
        """Send any immediate notifications for freshly available capacity."""

    def anchor_command(self) -> list[str] | None:
        """Return the subprocess command used to anchor idle windows."""
        return None

    def metadata(self, raw: Any, rows: list[UsageRow]) -> dict[str, Any]:
        """Return provider-specific structured metadata."""
        return {}

    def _available_now(self, rows: list[UsageRow]) -> bool:
        """Default availability check for 5h/7d window providers."""
        five_hour = next((row for row in rows if "5h" in row.identifier), None)
        seven_day = next((row for row in rows if "7d" in row.identifier), None)
        if seven_day and seven_day.is_exhausted:
            return False
        return not (five_hour and five_hour.is_exhausted)

    def _available_when(self, rows: list[UsageRow]) -> datetime | None:
        """Default next-available timestamp for 5h/7d window providers."""
        five_hour = next((row for row in rows if "5h" in row.identifier), None)
        seven_day = next((row for row in rows if "7d" in row.identifier), None)
        if seven_day and seven_day.is_exhausted and seven_day.reset_at:
            return seven_day.reset_at
        if five_hour and five_hour.is_exhausted and five_hour.reset_at:
            return five_hour.reset_at
        return None

    def availability(self, rows: list[UsageRow]) -> list[ModelAvailability]:
        """Return normalized provider availability entries."""
        available_now = self._available_now(rows)
        available_when = None if available_now else self._available_when(rows)
        return [
            ModelAvailability(
                name=self.provider_name(),
                available_now=available_now,
                available_when=available_when,
            )
        ]

    def collect_raw_and_rows(self, *, anchor: bool = False) -> tuple[Any, list[UsageRow]]:
        """Fetch provider data and optionally anchor the active window."""
        raw = self.fetch_raw()
        rows = self.to_rows(raw)

        if anchor and self.should_anchor(rows):
            command = self.anchor_command()
            if command and self._anchor_window(command):
                raw = self.fetch_raw()
                rows = self.to_rows(raw)

        return raw, rows

    def collect_snapshot(
        self,
        *,
        notify: bool = False,
        anchor: bool = False,
    ) -> ProviderSnapshot:
        """Collect a normalized provider snapshot."""
        raw, rows = self.collect_raw_and_rows(anchor=anchor)
        if notify:
            self.notify_always(rows)
            self._handle_notifications(rows)
        return ProviderSnapshot(
            provider=self.slug,
            display_name=self.name,
            status="ok",
            rows=rows,
            availability=self.availability(rows),
            metadata=self.metadata(raw, rows),
        )

    def render(self, rows: list[UsageRow], title: str | None = None) -> None:
        """Render the provider rows as a Rich table."""
        UsageTable().render(rows, title=title or self.name)

    def _anchor_window(self, command: list[str]) -> bool:
        """Run the anchoring command inside a temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                command,
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0

    def _handle_notifications(self, rows: list[UsageRow]) -> None:
        """Schedule an ntfy notification for the blocking reset window."""
        do_notify, blocking_reset = self.should_notify(rows)
        if not do_notify or blocking_reset is None:
            return

        notif_id = self._notification_id(rows)
        if self._notification_scheduled(notif_id):
            print("i  Notification already scheduled")
            return

        success, message = self._schedule_notification(
            reset_dt=blocking_reset,
            summary=f"{self.name} quota exhausted",
            notif_id=notif_id,
            title=f"{self.name} Session Reset",
        )
        if success:
            print(f"i  Notification scheduled for {message}")
        else:
            print(f"i  Failed to schedule notification: {message}")

    def should_notify(self, rows: list[UsageRow]) -> tuple[bool, datetime | None]:
        """Determine if a reset notification should be scheduled."""
        exhausted_resets = [
            row.reset_at for row in rows if row.is_exhausted and row.reset_at is not None
        ]
        if not exhausted_resets:
            return False, None
        return True, max(exhausted_resets)

    def send_ntfy(
        self,
        title: str,
        message: str,
        priority: str = "high",
        tags: str = "",
        at: str | None = None,
    ) -> tuple[bool, str | None]:
        """Send an ntfy notification immediately or in the future."""
        url = f"{self.ntfy_server}/{self.ntfy_topic}"
        headers: dict[str, str] = {
            "Title": title.encode("latin-1", "ignore").decode("latin-1").strip(),
            "Priority": priority,
        }
        if tags:
            headers["Tags"] = tags
        if at:
            headers["At"] = at
        try:
            response = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
            response.raise_for_status()
            return True, None
        except requests.RequestException as error:
            return False, str(error)

    def _schedule_notification(
        self,
        reset_dt: datetime,
        summary: str,
        notif_id: str,
        title: str = "Session Reset",
        tags: str = "white_check_mark,clock",
    ) -> tuple[bool, str]:
        """Schedule an ntfy notification at ``reset_dt`` plus one minute."""
        notify_dt = reset_dt + timedelta(minutes=1)
        at_time = str(int(notify_dt.timestamp()))
        full_tags = f"{tags},notif_id:{notif_id}" if notif_id else tags

        success, error = self.send_ntfy(
            title=title,
            message=f"{self.name} session reset!\n\n{summary}",
            priority="high",
            tags=full_tags,
            at=at_time,
        )
        if success:
            return True, notify_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        return False, error or "Unknown error"

    def _notification_id(self, rows: list[UsageRow]) -> str:
        """Deterministic notification ID from exhausted rows."""
        exhausted = sorted(
            (int(row.reset_at.timestamp()), row.identifier)
            for row in rows
            if row.is_exhausted and row.reset_at is not None
        )
        if not exhausted:
            return ""
        timestamp, _ = exhausted[-1]
        return f"{self.name.lower().replace(' ', '-')}-{timestamp}"

    def _notification_scheduled(self, notif_id: str) -> bool:
        """Return True if ntfy already has a scheduled message with this ID."""
        if not notif_id:
            return False
        url = f"{self.ntfy_server}/{self.ntfy_topic}/json"
        try:
            response = requests.get(url, params={"poll": "1", "sched": "1"}, timeout=10)
            response.raise_for_status()
            for line in response.text.strip().split("\n"):
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("event") == "message" and f"notif_id:{notif_id}" in message.get(
                    "tags", []
                ):
                    return True
        except requests.RequestException:
            pass
        return False

    def _state_file(self, name: str) -> Path:
        """Return the path to a named provider state file."""
        return self._state_path / f"{name}.json"

    def load_state(self, name: str) -> dict[str, Any]:
        """Load a named JSON state file."""
        path = self._state_file(name)
        if path.exists():
            try:
                return json.loads(path.read_text())  # type: ignore[no-any-return]
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def save_state(self, name: str, state: dict[str, Any]) -> None:
        """Persist a named JSON state file."""
        self._state_file(name).write_text(json.dumps(state, indent=2))
