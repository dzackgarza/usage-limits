from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Global OTLP sink DB path
DB_DIR = Path.home() / ".local" / "state" / "usage_sink"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = DB_DIR / "usage.db"


class TraceStore:
    """Manages OTLP traces in a lightweight SQLite database."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_FILE
        self._init_db()

    def _init_db(self) -> None:
        """Create the traces table if it does not exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    raw_json JSON
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captured_at ON traces(captured_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_provider ON traces(provider)")

    def add_trace(self, provider: str, raw_json: dict[str, Any]) -> None:
        """Add a trace (api_request event) to the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO traces (provider, raw_json)
                VALUES (?, ?)
                """,
                (provider, json.dumps(raw_json)),
            )

    def get_daily_counts(self, provider: str | None = None) -> dict[str, int]:
        """Return counts of api_request events per day."""
        query = """
            SELECT date(captured_at) as day, count(*)
            FROM traces
        """
        params: list[str] = []
        if provider:
            query += " WHERE provider = ?"
            params.append(provider)
        query += " GROUP BY day"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            return {row[0]: row[1] for row in cursor.fetchall()}

    def prune_stale(self) -> int:
        """Purge entries older than the current day's UTC midnight marker.
        Returns the number of rows deleted.
        """
        today_midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        limit = today_midnight.isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM traces WHERE captured_at < ?", (limit,))
            return cursor.rowcount

    def prune_old_traces(self, days: int = 7) -> None:
        """Prune traces older than X days to keep DB size small."""
        limit = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM traces WHERE captured_at < ?", (limit,))
