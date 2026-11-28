import json
from datetime import UTC, datetime
from pathlib import Path

from usage_limits.providers.antigravity import AntigravityAccount

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_optional_summary_reset_preserves_recovered_gemini_quota() -> None:
    raw = json.loads(
        (FIXTURE_DIR / "antigravity-quota-summary-optional-reset.json").read_text()
    )

    rows = AntigravityAccount(account_id="test@example.com").to_rows(raw)

    assert [(row.identifier, row.pct_used, row.reset_at) for row in rows] == [
        (
            "Gemini Models (5h)",
            41,
            datetime(2026, 11, 28, 13, 7, 12, tzinfo=UTC),
        ),
        ("Claude and GPT models (5h)", 0, None),
        ("Claude and GPT models (Weekly)", 0, None),
    ]
