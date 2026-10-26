"""ChatGPT Pro accounting uses conversation graph structure, never message text."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fixtures.chatgpt_pro_history import CAPTURED_NODES
from usage_limits.providers.chatgpt_pro import (
    Author,
    ChatGPTClient,
    ChatGPTProProvider,
    Conversation,
    Ledger,
    Message,
    MessageMetadata,
    Node,
    ProFinal,
    ProjectPage,
    extract_finals,
)
from usage_limits.registry import get_provider_class, list_providers


def test_project_pagination_covers_only_updated_history() -> None:
    page = ProjectPage.model_validate(
        {
            "items": [
                {"id": "recent", "update_time": "2026-10-24T12:00:00Z"},
                {"id": "previous", "update_time": "2026-10-23T12:00:00Z"},
            ],
            "cursor": "next",
        }
    )
    assert page.needs_next_page(datetime(2026, 10, 22, tzinfo=UTC))
    assert not page.needs_next_page(datetime(2026, 10, 24, tzinfo=UTC))
    page.items.reverse()
    with pytest.raises(ValueError):
        page.needs_next_page(datetime(2026, 10, 24, tzinfo=UTC))


def test_captured_history_counts_completed_pro_messages() -> None:
    nodes = {
        str(key): Node(
            parent=str(parent) if parent is not None else None,
            children=[str(child) for child, child_parent, *_ in CAPTURED_NODES if child_parent == key],
            message=Message(
                id=str(key),
                author=Author(role=role),
                create_time=timestamp,
                status="finished_successfully",
                end_turn=end_turn,
                recipient=recipient,
                metadata=MessageMetadata(model_slug="gpt-6-pro", turn_exchange_id=f"exchange-{key < 30}"),
            ),
        )
        for key, parent, role, timestamp, end_turn, recipient in CAPTURED_NODES
    }
    finals = extract_finals(Conversation(mapping=nodes, current_node="35"), "conversation", "salt")
    assert len(finals) == 2
    assert len({final.group for final in finals.values()}) == 2
    assert sorted(final.timestamp for final in finals.values()) == [
        1792827339.529985,
        1792827630.855292,
    ]


def test_serial_tool_continuations_share_interaction() -> None:
    # Minimal structural example from issue 3436's two-final interaction.
    def message(key: str, role: str, *, final: bool) -> Message:
        return Message(
            id=key,
            author=Author(role=role),
            create_time=100,
            status="finished_successfully",
            end_turn=final,
            recipient="all",
            metadata=MessageMetadata(model_slug="gpt-6-pro", turn_exchange_id="exchange"),
        )

    nodes = {
        "user": Node(
            parent=None,
            children=["first"],
            message=message("user", "user", final=False),
        ),
        "first": Node(
            parent="user",
            children=["tool"],
            message=message("first", "assistant", final=True),
        ),
        "tool": Node(
            parent="first",
            children=["last"],
            message=message("tool", "tool", final=False),
        ),
        "last": Node(parent="tool", children=[], message=message("last", "assistant", final=True)),
    }
    graph = Conversation(mapping=nodes, current_node="last")
    finals = extract_finals(graph, "conversation", "salt")
    assert len(finals) == 2
    assert len({final.group for final in finals.values()}) == 1

    # A regenerated answer introduces a second visible branch.
    nodes["user"].children.append("alternate")
    graph.mapping["alternate"] = Node(
        parent="user",
        children=[],
        message=message("alternate", "assistant", final=True),
    )
    finals = extract_finals(graph, "conversation", "salt")
    assert len(finals) == 3
    assert len({final.group for final in finals.values()}) == 3


def test_history_range_does_not_assert_exhaustion() -> None:
    now = datetime(2026, 10, 24, tzinfo=UTC)
    ledger = Ledger(
        account="account",
        salt="salt",
        observed_at=now,
        finals={str(i): ProFinal(timestamp=now.timestamp() - 1, model="gpt-6-pro", group="interaction") for i in range(12)},
    )
    provider = ChatGPTProProvider.__new__(ChatGPTProProvider)
    raw = provider.summarize(ledger, now, limit=10)
    assert raw["interactions"] == 1
    assert raw["raw_finals"] == 12
    assert raw["remaining_min"] == 0
    assert raw["remaining_max"] == 9
    (row,) = provider.to_rows(raw)
    assert "1–12 / 10" in row.identifier
    assert "Estimated" in row.identifier
    assert not row.is_exhausted
    assert row.reset_at is None
    assert provider.availability([row]) == []

    ledger.finals = {key: final.model_copy(update={"group": key}) for key, final in ledger.finals.items()}
    (row,) = provider.to_rows(provider.summarize(ledger, now, limit=10))
    assert row.pct_used == 100
    assert not row.is_exhausted
    assert row.model_dump()["is_exhausted"] is False


def test_server_reset_anchors_window_and_blocked_access() -> None:
    now = datetime(2026, 10, 24, tzinfo=UTC)
    reset = now + timedelta(hours=1)
    ledger = Ledger(
        account="account",
        salt="salt",
        observed_at=now,
        server_reset=reset,
        last_blocked_at=now,
        finals={
            "old": ProFinal(
                timestamp=(reset - timedelta(days=7, seconds=1)).timestamp(),
                model="gpt-6-pro",
                group="old",
            )
        },
    )
    provider = ChatGPTProProvider.__new__(ChatGPTProProvider)
    raw = provider.summarize(ledger, now, limit=50)
    assert raw["raw_finals"] == 0
    assert raw["window_start"] == (reset - timedelta(days=7)).isoformat()
    assert raw["window_basis"] == "server-reset-minus-seven-days"
    assert raw["remaining_max"] == 0
    (row,) = provider.to_rows(raw)
    assert row.is_exhausted
    assert row.reset_at == reset
    (availability,) = provider.availability([row])
    assert not availability.available_now
    assert availability.available_when == reset

    after = reset + timedelta(seconds=1)
    raw = provider.summarize(ledger, after, limit=50)
    assert not raw["blocked"]
    assert raw["server_reset"] is None
    assert raw["window_basis"] == "provisional-rolling-seven-days"


def test_chatgpt_pro_is_in_default_collection() -> None:
    assert get_provider_class("chatgpt-pro") is ChatGPTProProvider
    (registered,) = [provider for provider in list_providers() if provider.provider == "chatgpt-pro"]
    assert registered.active


def test_missing_login_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ChatGPTClient(tmp_path / "auth.json")


def test_missing_current_node_fails_instead_of_returning_zero() -> None:
    conversation = Conversation.model_validate({"mapping": {}, "current_node": "missing"})
    with pytest.raises(KeyError):
        extract_finals(conversation, "conversation", "salt")
