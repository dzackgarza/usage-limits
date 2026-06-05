"""Provider normalization tests for Ollama."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from usage_limits.providers.ollama import OllamaProvider

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_ollama_to_rows_extracts_session_and_weekly_windows() -> None:
    provider = OllamaProvider()
    html = (FIXTURE_DIR / "ollama-settings.html").read_text()
    rows = provider.to_rows({"html": html})

    assert len(rows) == 2

    five_hour = next(r for r in rows if "5h" in r.identifier)
    assert five_hour.pct_used == 42.0
    assert five_hour.is_exhausted is False
    assert five_hour.reset_at == datetime.fromisoformat("2030-01-15T12:00:00+00:00")

    seven_day = next(r for r in rows if "7d" in r.identifier)
    assert seven_day.pct_used == 100.0
    assert seven_day.is_exhausted is True
    assert seven_day.reset_at == datetime.fromisoformat("2030-01-15T12:00:00+00:00")
