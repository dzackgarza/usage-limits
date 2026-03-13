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
                    trace_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    raw_json JSON,
                    PRIMARY KEY (trace_id, span_id)
                )
                """
            )
            # Index for fast daily counts
            conn.execute("CREATE INDEX IF NOT EXISTS idx_captured_at ON traces(captured_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_provider ON traces(provider)")

    def add_trace(
        self,
        trace_id: str,
        span_id: str,
        provider: str,
        raw_json: dict[str, Any],
    ) -> bool:
        """Add a trace to the database, deduplicating by trace_id + span_id."""
        captured_at = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO traces (trace_id, span_id, provider, captured_at, raw_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (trace_id, span_id, provider, captured_at, json.dumps(raw_json)),
                )
                return True
            except sqlite3.IntegrityError:
                # Already exists (deduplicated)
                return False

    def get_daily_counts(self, provider: str | None = None) -> dict[str, int]:
        """Return counts of traces per day for the given provider."""
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

    def prune_old_traces(self, days: int = 7) -> None:
        """Prune traces older than X days to keep DB size small."""
        limit = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM traces WHERE captured_at < ?", (limit,))
