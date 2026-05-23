"""Claude Code usage provider caching tests.

Caching is critical for Claude because the Anthropic API rate-limits
aggressively. With TTL=300, two rapid calls must produce consistent
results — the second reads from cache instead of hitting the API again.
"""

from __future__ import annotations

from usage_limits.registry import collect_provider


def test_claude_caching_produces_consistent_results() -> None:
    """Two rapid calls must agree on status and cached timestamp.

    If the first call succeeds, the second returns cached data (same
    ``last_updated``).  If the first is rate-limited, the second also
    returns a rate-limit error (no double-hitting, just consistency).
    """
    first = collect_provider("claude")
    second = collect_provider("claude")

    # Same status — whatever it is — proves caching didn't introduce
    # inconsistency (e.g. first OK then 429, or first 429 then OK).
    assert first.status == second.status, (
        f"Cached result diverged: {first.status} -> {second.status}\n"
        f"First errors: {first.errors}\nSecond errors: {second.errors}"
    )

    # When data IS available, cache hit must preserve last_updated.
    if first.status == "ok":
        assert "last_updated" in first.metadata
        assert first.metadata["last_updated"] == second.metadata["last_updated"], (
            "Cache miss: last_updated changed between calls"
        )
