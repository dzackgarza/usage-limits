"""Provider normalization tests for Qoder.

Uses a captured API response shape to exercise the
``fetch_raw`` → ``to_rows`` pipeline. The fixture shape
matches the Qoder secret storage format from state.vscdb.
"""

from __future__ import annotations

import json
from pathlib import Path

from usage_limits.providers.qoder import QoderProvider

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_qoder_to_rows_with_captured_fixture() -> None:
    provider = QoderProvider()
    raw = json.loads((FIXTURE_DIR / "qoder-usage.json").read_text())
    rows = provider.to_rows(raw)

    assert len(rows) == 3

    # User quota row
    user = rows[0]
    assert user.identifier == "Qoder (Pro - dzackgarza@gmail.com)"
    assert user.pct_used == 37.5  # 750/2000
    assert user.is_exhausted is False
    assert user.reset_at is None

    # Add-on quota row
    addon = rows[1]
    assert addon.identifier == "Qoder (Add-on - dzackgarza@gmail.com)"
    assert addon.pct_used == 10.0  # 50/500
    assert addon.is_exhausted is False
    assert addon.reset_at is None

    # Total usage row
    total = rows[2]
    assert total.identifier == "Qoder (Total - dzackgarza@gmail.com)"
    assert total.pct_used == 40.0
    assert total.is_exhausted is False
    assert total.reset_at is None
