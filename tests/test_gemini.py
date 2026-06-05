"""Provider normalization tests for Gemini CLI.

Uses a fixture matching the documented ``retrieveUserQuota`` response
shape from the cockpit-tools Rust source to exercise the
``to_rows`` pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

from usage_limits.providers.gemini import GeminiAccount

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_gemini_to_rows_parses_buckets() -> None:
    """to_rows produces one row per bucket with correct pct_used."""
    provider = GeminiAccount(account_id="test@example.com")
    raw = json.loads((FIXTURE_DIR / "gemini-quota.json").read_text())
    rows = provider.to_rows(raw)

    assert len(rows) == 3

    # Gemini 2.0 Flash: remainingFraction=0.85 → pct_used = (1-0.85)*100 = 15
    flash = {
        r.identifier: r for r in rows if "2.0 Flash" in r.identifier and "Lite" not in r.identifier
    }
    assert len(flash) == 1
    flash_row = next(iter(flash.values()))
    assert flash_row.pct_used == 15
    assert flash_row.is_exhausted is False
    assert flash_row.reset_at is not None

    # Gemini 2.5 Pro: remainingFraction=0.42 → pct_used = (1-0.42)*100 = 58
    pro = {r.identifier: r for r in rows if "2.5 Pro" in r.identifier}
    assert len(pro) == 1
    pro_row = next(iter(pro.values()))
    assert pro_row.pct_used == 58
    assert pro_row.is_exhausted is False
    assert pro_row.reset_at is not None

    # Gemini 2.0 Flash Lite: remainingFraction=0.0 → pct_used = 100
    lite = {r.identifier: r for r in rows if "Flash Lite" in r.identifier}
    assert len(lite) == 1
    lite_row = next(iter(lite.values()))
    assert lite_row.pct_used == 100
    assert lite_row.is_exhausted is True
    assert lite_row.reset_at is not None


def test_gemini_to_rows_sorted_alphabetically() -> None:
    """Rows are sorted alphabetically by identifier."""
    provider = GeminiAccount(account_id="test@example.com")
    raw = json.loads((FIXTURE_DIR / "gemini-quota.json").read_text())
    rows = provider.to_rows(raw)

    identifiers = [r.identifier for r in rows]
    assert identifiers == sorted(identifiers)


def test_gemini_to_rows_model_names_human_readable() -> None:
    """ModelIds like 'models/gemini-2.0-flash' convert to 'Gemini 2.0 Flash'."""
    provider = GeminiAccount(account_id="test@example.com")
    raw = json.loads((FIXTURE_DIR / "gemini-quota.json").read_text())
    rows = provider.to_rows(raw)

    identifiers = {r.identifier for r in rows}
    assert "Gemini 2.0 Flash" in identifiers
    assert "Gemini 2.5 Pro" in identifiers
    assert "Gemini 2.0 Flash Lite" in identifiers


def test_gemini_availability_uses_most_used_model() -> None:
    """availability reflects the most exhausted model."""
    provider = GeminiAccount(account_id="test@example.com")
    raw = json.loads((FIXTURE_DIR / "gemini-quota.json").read_text())
    rows = provider.to_rows(raw)
    avail = provider.availability(rows)

    assert len(avail) == 1
    assert avail[0].name == "Gemini CLI"
    # Flash Lite is at 100%, so not available now
    assert avail[0].available_now is False
    assert avail[0].available_when is not None


def test_gemini_should_anchor() -> None:
    """should_anchor always returns False."""
    provider = GeminiAccount(account_id="test@example.com")
    assert provider.should_anchor([]) is False


def test_gemini_provider_name_and_slug() -> None:
    """Provider metadata is correct."""
    assert GeminiAccount.slug == "gemini-cli"
    assert GeminiAccount.name == "Gemini CLI"
    assert GeminiAccount(account_id="x@y.com").provider_name() == "Gemini CLI"


def test_gemini_bucket_model_name() -> None:
    """_bucket_model_name strips 'models/' prefix and formats nicely."""
    from usage_limits.providers.gemini import BucketInfo

    bucket = BucketInfo(
        modelId="models/gemini-2.0-flash",
        remainingFraction=0.5,
        resetTime="2026-06-07T00:00:00Z",
        tokenType="REQUESTS",
    )
    name = GeminiAccount._bucket_model_name(bucket)
    assert name == "Gemini 2.0 Flash"
