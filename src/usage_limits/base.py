"""Abstract base class for all usage-limit providers."""

from __future__ import annotations

import json
import subprocess
import tempfile
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from usage_limits.contracts import ProviderSnapshot
from usage_limits.table import ModelAvailability, UsageRow, UsageTable

__all__ = ["ProviderAccount", "UsageProvider"]


class UsageProvider(ABC):
    """Abstract base for all usage-limit providers."""

    slug: str
    name: str
    state_dir: str
    cache_ttl_seconds: int = 0
    """How long (in seconds) a cached ``fetch_raw()`` response is considered fresh.
    0 means the cache expires immediately — every call re-fetches."""
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
        """Usable only when no window is exhausted."""
        return not any(row.is_exhausted for row in rows)

    def _available_when(self, rows: list[UsageRow]) -> datetime | None:
        """Earliest time all exhausted windows will have reset."""
        reset_times = [
            row.reset_at for row in rows if row.is_exhausted and row.reset_at is not None
        ]
        return max(reset_times) if reset_times else None

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
        """Fetch provider data (with caching) and optionally anchor the active window."""
        raw, last_updated = self._fetch_with_cache()

        rows = self.to_rows(raw)

        if anchor and self.should_anchor(rows):
            command = self.anchor_command()
            if command and self._anchor_window(command):
                raw, last_updated = self._fetch_with_cache(force=True)
                rows = self.to_rows(raw)

        self._last_updated = last_updated
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
        meta = self.metadata(raw, rows)
        if self._last_updated is not None:
            meta["last_updated"] = self._last_updated.isoformat()
        return ProviderSnapshot(
            provider=self.slug,
            display_name=self.name,
            status="ok",
            rows=rows,
            availability=self.availability(rows),
            metadata=meta,
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

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    _last_updated: datetime | None = None

    def _get_cache_path(self) -> Path:
        """Path to the fetch-result cache file."""
        return self._state_file("_fetch_cache")

    def _read_cache(self, *, ignore_ttl: bool = False) -> tuple[Any, datetime] | None:
        """Return (raw, last_updated) if a cache entry with data exists, else None.

        Returns None for entries that only contain an error (raw is None) —
        those trigger a live fetch on the next attempt.

        When *ignore_ttl* is true the TTL freshness check is skipped —
        used to fall back to stale data when a live fetch fails.
        """
        path = self._get_cache_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        last_updated = datetime.fromisoformat(data["last_updated"])
        if (
            not ignore_ttl
            and (datetime.now(UTC) - last_updated).total_seconds() >= self.cache_ttl_seconds
        ):
            return None  # stale
        raw = data.get("raw")
        if raw is None:
            return None  # cached error, no data to return
        return raw, last_updated

    def _write_cache(self, raw: Any) -> datetime:
        """Persist raw fetch data with the current timestamp, clearing any prior error.

        Returns ``now``.
        """
        now = datetime.now(UTC)
        self._get_cache_path().write_text(json.dumps({"raw": raw, "last_updated": now.isoformat()}))
        return now

    def _write_cache_error(self, exc: BaseException) -> datetime:
        """Persist a fetch failure and preserve any existing raw data for stale fallback.

        The error entry marks the cache as dirty so ``_read_cache``
        returns ``None``, forcing the next call to attempt a live fetch.
        Returns ``now``.
        """
        now = datetime.now(UTC)
        path = self._get_cache_path()

        # Preserve prior raw data so stale fallback still works
        raw: Any = None
        if path.exists():
            try:
                prior = json.loads(path.read_text())
                raw = prior.get("raw")
            except (json.JSONDecodeError, OSError):
                pass

        entry: dict[str, Any] = {}
        if raw is not None:
            entry["raw"] = raw
        else:
            entry["raw"] = None
        entry["error_type"] = type(exc).__name__
        entry["error_message"] = str(exc)
        entry["last_updated"] = now.isoformat()
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            entry["error_status_code"] = exc.response.status_code
        path.write_text(json.dumps(entry))
        return now

    def _fetch_with_cache(self, *, force: bool = False) -> tuple[Any, datetime]:
        """Return (raw, last_updated), reading from cache when possible.

        Cached GOOD data is served within TTL to prevent API hammering.
        Cached errors are never served — they always trigger a live fetch.
        On live-fetch failure, stale GOOD data is served as a fallback.

        Order of preference:
        1. Fresh GOOD cache (within TTL)
        2. Live fetch — persists GOOD data on success, error on failure
        3. Stale GOOD cache — fallback when live fetch fails
        4. Propagate exception — when no data exists at all
        """
        if not force:
            cached = self._read_cache()
            if cached is not None:
                return cached

        try:
            raw = self.fetch_raw()
        except BaseException as exc:
            self._write_cache_error(exc)
            cached = self._read_cache(ignore_ttl=True)
            if cached is not None:
                return cached
            raise

        last_updated = self._write_cache(raw)
        return raw, last_updated


class ProviderAccount(UsageProvider, ABC):
    """Provider bound to a specific account.

    Single-account providers use ``account_id="default"``.
    Multi-account providers create one instance per account identifier.
    """

    def __init__(self, account_id: str = "default") -> None:
        super().__init__()
        self.account_id = account_id

    def collect_snapshot(
        self,
        *,
        notify: bool = False,
        anchor: bool = False,
    ) -> ProviderSnapshot:
        snap = super().collect_snapshot(notify=notify, anchor=anchor)
        return snap.model_copy(update={"account": self.account_id})

    @classmethod
    def resolve_accounts(cls) -> list[ProviderAccount]:
        """Return one ProviderAccount instance per known credential.

        Single-account providers return ``[cls()]``.
        Multi-account providers override to return one per account.
        """
        return [cls()]
