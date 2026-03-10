"""CLI smoke tests for usage_limits."""

from __future__ import annotations

import json
import subprocess
import sys


def test_module_cli_lists_registered_providers_as_json() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "usage_limits", "providers", "list", "--json"],
        capture_output=True,
        check=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert [entry["provider"] for entry in payload[:4]] == [
        "amp",
        "antigravity",
        "claude",
        "codex",
    ]
    assert payload[0]["display_name"] == "Amp"
