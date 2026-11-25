"""CLI smoke tests for usage_limits."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


def test_cli_runs_full_collection_pipeline() -> None:
    """Invoke usage-limits on one provider via the actual CLI entrypoint."""
    result = subprocess.run(
        [sys.executable, "-m", "usage_limits", "--provider", "opencode-zen"],
        capture_output=True,
        check=True,
        text=True,
    )
    assert "OpenCode Zen" in result.stdout
    assert "0%" in result.stdout or "100%" in result.stdout


def test_module_cli_lists_registered_providers_as_json() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "usage_limits", "providers", "list", "--json"],
        capture_output=True,
        check=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert [entry["provider"] for entry in payload[:3]] == [
        "agy-secret-pool",
        "antigravity",
        "claude",
    ]
    assert payload[0]["display_name"] == "Agy Secret Pool"
    assert "gemini-cli" not in {entry["provider"] for entry in payload}


def test_cli_fetch_failure_replaces_stale_cache_and_is_retried(tmp_path: Path) -> None:
    """An expired snapshot and a fresh error entry both require a real fetch."""
    env = {**os.environ, "HOME": str(tmp_path)}
    cache = tmp_path / ".local/state/claude_usage/default/_fetch_cache.json"
    cache.parent.mkdir(parents=True)
    raw = json.loads(
        (Path(__file__).parent / "fixtures/claude_response.json").read_text()
    )
    stale_at = datetime.now(UTC) - timedelta(minutes=10)
    cache.write_text(json.dumps({"raw": raw, "last_updated": stale_at.isoformat()}))

    command = [sys.executable, "-m", "usage_limits", "--provider", "claude", "--json"]
    error_timestamps = []
    for _ in range(2):
        result = subprocess.run(
            command, env=env, capture_output=True, check=True, text=True
        )
        (snapshot,) = json.loads(result.stdout)["providers"]
        assert snapshot["status"] == "error"
        assert snapshot["rows"] == []
        (error,) = snapshot["errors"]
        assert error["type"] == "filenotfounderror"
        assert (
            str(tmp_path / ".config/usage-limits/credentials/claude/default.json")
            in error["message"]
        )

        entry = json.loads(cache.read_text())
        assert entry["raw"] is None
        assert entry["error_type"] == "FileNotFoundError"
        error_timestamps.append(datetime.fromisoformat(entry["last_updated"]))

    assert stale_at < error_timestamps[0] < error_timestamps[1]
