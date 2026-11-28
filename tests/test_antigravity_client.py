from usage_limits.providers.antigravity import AntigravityAccount


def test_versioned_client_identity_restores_gemini_summary_windows() -> None:
    provider = AntigravityAccount.resolve_accounts()[0]

    rows = provider.to_rows(provider.fetch_raw())
    by_id = {row.identifier: row for row in rows}

    assert set(by_id) == {
        "Gemini Models (5h)",
        "Gemini Models (Weekly)",
        "Claude and GPT models (5h)",
        "Claude and GPT models (Weekly)",
    }
    assert (
        by_id["Gemini Models (5h)"].reset_at != by_id["Gemini Models (Weekly)"].reset_at
    )
