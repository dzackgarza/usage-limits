"""Content-free reconstruction of ChatGPT Pro message usage.

Accounting reference: https://github.com/steipete/CodexBar/issues/3436
Browser transport reference: skillsynchq/txcript, src/harness/chatgpt.rs.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal, TypedDict, cast
from urllib.parse import quote, urlencode

import requests
from curl_cffi import requests as browser_requests
from pydantic import BaseModel, Field, JsonValue, computed_field, model_validator

from usage_limits.base import ProviderAccount, _write_json_atomic
from usage_limits.config import resolve_path, settings
from usage_limits.table import ModelAvailability, UsageRow

PRO_MODELS = frozenset({"gpt-5-5-pro", "gpt-5-6-pro", "gpt-6-pro"})
WEEK = timedelta(days=7)
ORIGIN = "https://chatgpt.com"


class AccountClaim(BaseModel):
    chatgpt_account_id: str


class TokenClaims(BaseModel):
    auth: AccountClaim = Field(alias="https://api.openai.com/auth")


class Tokens(BaseModel):
    access_token: str = Field(min_length=1)
    account_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def same_account(self) -> Tokens:
        # txcript's account_id_from_token reads this same OAuth JWT claim.
        encoded = self.access_token.split(".")[1]
        claims = TokenClaims.model_validate(json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))))
        if claims.auth.chatgpt_account_id != self.account_id:
            raise ValueError("ChatGPT token account differs from its credential account")
        return self


class AuthFile(BaseModel):
    auth_mode: Literal["chatgpt"]
    tokens: Tokens


class Author(BaseModel):
    role: str


class MessageMetadata(BaseModel):
    model_slug: str | None = None
    resolved_model_slug: str | None = None
    is_visually_hidden_from_conversation: bool = False
    turn_exchange_id: str | None = None


class Message(BaseModel):
    id: str
    author: Author
    create_time: float | None
    status: str
    end_turn: bool | None = None
    recipient: str | None = None
    metadata: MessageMetadata


class Node(BaseModel):
    parent: str | None
    children: list[str]
    message: Message | None


class Conversation(BaseModel):
    mapping: dict[str, Node]
    current_node: str


class IndexItem(BaseModel):
    id: str
    update_time: datetime


class HistoryPage(BaseModel):
    items: list[IndexItem]
    total: int


class ProjectPage(BaseModel):
    items: list[IndexItem]
    cursor: str | None

    def needs_next_page(self, cutoff: datetime) -> bool:
        """Stop an ordered history scan once it reaches already-covered activity."""
        if self.cursor is None:
            return False
        if not self.items:
            raise ValueError("ChatGPT project history returned an empty nonterminal page")
        timestamps = [item.update_time for item in self.items]
        if timestamps != sorted(timestamps, reverse=True):
            raise ValueError("ChatGPT project history is not ordered by update time")
        return timestamps[-1] >= cutoff


class GizmoId(BaseModel):
    id: str


class Gizmo(BaseModel):
    gizmo: GizmoId


class Project(BaseModel):
    gizmo: Gizmo


class SidebarPage(BaseModel):
    items: list[Project]
    cursor: str | None


class ModelLimit(BaseModel):
    model_slug: str
    resets_after: datetime


class InitResponse(BaseModel):
    model_limits: list[ModelLimit]


class ProFinal(BaseModel):
    timestamp: float
    model: str
    group: str


class Ledger(BaseModel):
    account: str
    salt: str
    observed_at: datetime
    conversations: dict[str, datetime] = Field(default_factory=dict)
    finals: dict[str, ProFinal] = Field(default_factory=dict)
    server_reset: datetime | None = None
    last_blocked_at: datetime | None = None
    first_unblocked_at: datetime | None = None


class ProUsage(TypedDict):
    interactions: int
    raw_finals: int
    limit: int
    remaining_min: int
    remaining_max: int
    window_start: str
    window_end: str
    window_basis: str
    blocked: bool
    server_reset: str | None
    observed_at: str


class ChatGPTProRow(UsageRow):
    """A message estimate cannot establish whether access is exhausted."""

    server_blocked: bool = Field(exclude=True)

    def _is_exhausted(self) -> bool:
        return self.server_blocked

    is_exhausted = computed_field(property(_is_exhausted))


def _digest(salt: str, value: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def _ancestry(conversation: Conversation, start: str) -> list[str]:
    """Validate graph links and reject cycles before using branch membership."""
    path: list[str] = []
    seen: set[str] = set()
    current: str | None = start
    while current is not None:
        if current in seen:
            raise ValueError("ChatGPT conversation contains a parent cycle")
        seen.add(current)
        path.append(current)
        current = conversation.mapping[current].parent
    return path


def extract_finals(conversation: Conversation, conversation_id: str, salt: str) -> dict[str, ProFinal]:
    """Retain all strict finals; collapse only structurally supported serial groups.

    Issue 3436's multi-final examples require the same nearest user, exchange,
    model, active branch, and internal/tool continuation. Alternate branches and
    ambiguous forks retain distinct interaction keys.
    """
    active = set(_ancestry(conversation, conversation.current_node))
    candidates: dict[tuple[str, str, str], list[str]] = {}
    finals: dict[str, ProFinal] = {}
    for node_id, node in conversation.mapping.items():
        message = node.message
        if message is None:
            continue
        metadata = message.metadata
        model = metadata.resolved_model_slug or metadata.model_slug
        if (
            message.author.role != "assistant"
            or message.status != "finished_successfully"
            or message.end_turn is not True
            or message.recipient not in (None, "all")
            or metadata.is_visually_hidden_from_conversation
            or model not in PRO_MODELS
        ):
            continue
        if message.create_time is None:
            raise ValueError("Completed Pro message has no timestamp")
        key = _digest(salt, f"{conversation_id}:{message.id}")
        finals[key] = ProFinal(timestamp=message.create_time, model=model, group=key)
        path = _ancestry(conversation, node_id)
        user = next(
            (ancestor for ancestor in path if (m := conversation.mapping[ancestor].message) is not None and m.author.role == "user"),
            None,
        )
        if user is None or metadata.turn_exchange_id is None or node_id not in active:
            continue
        segment = path[: path.index(user) + 1]
        if any(len(conversation.mapping[ancestor].children) > 1 for ancestor in segment):
            continue
        if any(
            (other := conversation.mapping[ancestor].message) is not None
            and other.author.role == "assistant"
            and other.end_turn is True
            and other.recipient in (None, "all")
            and not other.metadata.is_visually_hidden_from_conversation
            and (other.metadata.resolved_model_slug or other.metadata.model_slug) != model
            for ancestor in segment
        ):
            continue
        candidates.setdefault((user, metadata.turn_exchange_id, model), []).append(node_id)

    for (user, exchange, model), members in candidates.items():
        if len(members) < 2:
            continue
        # Require internal/tool continuation between every pair of serial finals.
        ordered = sorted(members, key=lambda member: len(_ancestry(conversation, member)))
        supported = True
        for before, after in zip(ordered, ordered[1:]):
            path = _ancestry(conversation, after)
            between = path[1 : path.index(before)]
            if not any((m := conversation.mapping[ancestor].message) is not None and (m.author.role == "tool" or m.recipient not in (None, "all")) for ancestor in between):
                supported = False
        if not supported:
            continue
        group = _digest(salt, f"{conversation_id}:{user}:{exchange}:{model}")
        for member in members:
            message = conversation.mapping[member].message
            assert message is not None
            finals[_digest(salt, f"{conversation_id}:{message.id}")].group = group
    return finals


class ChatGPTClient:
    """Read Codex-owned auth and space every request, including a 401 retry."""

    def __init__(self, auth_path: Path, cooldown_path: Path) -> None:
        self.auth_path = auth_path
        self.cooldown_path = cooldown_path
        self.tokens = AuthFile.model_validate_json(auth_path.read_text()).tokens
        self.session = browser_requests.Session(impersonate="chrome")
        self.last_request = 0.0
        self.requests = 0

    def close(self) -> None:
        self.session.close()

    def request(self, path: str, *, initialize: bool = False) -> JsonValue:
        for attempt in range(2):
            if self.cooldown_path.exists():
                retry_at = float(self.cooldown_path.read_text())
                if time.time() < retry_at:
                    raise RuntimeError(f"ChatGPT rate-limit cooldown until {datetime.fromtimestamp(retry_at, UTC).isoformat()}")
            if self.requests >= 200:
                raise RuntimeError("ChatGPT history request budget exceeded; ledger remains unchanged")
            time.sleep(max(0.0, self.last_request + 1.0 - time.monotonic()))
            self.last_request = time.monotonic()
            self.requests += 1
            response = self.session.request(
                "POST" if initialize else "GET",
                ORIGIN + path,
                headers={
                    "Authorization": f"Bearer {self.tokens.access_token}",
                    "ChatGPT-Account-ID": self.tokens.account_id,
                    "originator": "usage-limits",
                    "Accept": "application/json",
                    "Referer": ORIGIN + "/",
                },
                json={"model": "gpt-6-pro", "timezone_offset_min": 0, "timezone": "UTC"} if initialize else None,
                allow_redirects=False,
                timeout=30,
            )
            if response.status_code == 401 and attempt == 0:
                updated = AuthFile.model_validate_json(self.auth_path.read_text()).tokens
                if updated.account_id != self.tokens.account_id:
                    raise ValueError("ChatGPT credential changed accounts during collection")
                if updated.access_token != self.tokens.access_token:
                    self.tokens = updated
                    continue
            if response.status_code == 429:
                retry = response.headers.get("Retry-After")
                delay = 300.0
                if retry is not None:
                    retry_seconds = float(retry) if retry.isdecimal() else parsedate_to_datetime(retry).timestamp() - time.time()
                    delay = max(delay, retry_seconds)
                _write_json_atomic(self.cooldown_path, time.time() + delay)
            if response.status_code != 200:
                error_response = requests.Response()
                error_response.status_code = response.status_code
                error_response.headers.update({name: value for name, value in response.headers.items() if value is not None})
                raise requests.HTTPError(
                    f"ChatGPT HTTP {response.status_code}; history usage unavailable",
                    response=error_response,
                )
            return cast(JsonValue, response.json())
        raise AssertionError("Unreachable credential retry state")

    def history(self, cutoff: datetime) -> dict[str, IndexItem]:
        conversations: dict[str, IndexItem] = {}
        for archived in (False, True):
            offset = 0
            while True:
                query = urlencode(
                    {
                        "offset": offset,
                        "limit": 100,
                        "order": "updated",
                        "is_archived": str(archived).lower(),
                    }
                )
                page = HistoryPage.model_validate(self.request("/backend-api/conversations?" + query))
                for item in page.items:
                    if item.update_time >= cutoff:
                        conversations[item.id] = item
                offset += len(page.items)
                if offset >= page.total or (page.items and page.items[-1].update_time < cutoff):
                    break
                if not page.items:
                    raise ValueError("ChatGPT history pagination stopped before its total")

        projects: set[str] = set()
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            sidebar_query = {"owned_only": "true", "conversations_per_gizmo": "0"}
            if cursor is not None:
                sidebar_query["cursor"] = cursor
            sidebar = SidebarPage.model_validate(self.request("/backend-api/gizmos/snorlax/sidebar?" + urlencode(sidebar_query)))
            projects.update(item.gizmo.gizmo.id for item in sidebar.items)
            cursor = sidebar.cursor
            if cursor is None:
                break
            if cursor in seen:
                raise ValueError("ChatGPT project sidebar repeated a cursor")
            seen.add(cursor)
        for project in sorted(projects):
            cursor = "0"
            seen = set()
            while True:
                page_project = ProjectPage.model_validate(self.request(f"/backend-api/gizmos/{quote(project, safe='')}/conversations?" + urlencode({"cursor": cursor})))
                for item in page_project.items:
                    if item.update_time >= cutoff:
                        previous = conversations.get(item.id)
                        if previous is None or previous.update_time < item.update_time:
                            conversations[item.id] = item
                if not page_project.needs_next_page(cutoff):
                    break
                assert page_project.cursor is not None
                if page_project.cursor in seen:
                    raise ValueError("ChatGPT project history repeated a cursor")
                seen.add(cursor)
                cursor = page_project.cursor
        return conversations


class ChatGPTProProvider(ProviderAccount):
    """History estimates remain separate from the Codex quota provider."""

    slug = "chatgpt-pro"
    name = "ChatGPT Pro"
    state_dir = "chatgpt_pro_usage"
    cache_ttl_seconds = 300

    def __init__(self) -> None:
        auth_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        self.auth_path = resolve_path(settings.chatgpt_pro.auth_file) if settings.chatgpt_pro.auth_file is not None else auth_home / "auth.json"
        tokens = AuthFile.model_validate_json(self.auth_path.read_text()).tokens
        super().__init__(account_id=_digest("chatgpt-pro", tokens.account_id))

    def provider_name(self) -> str:
        return self.name

    def should_anchor(self, rows: list[UsageRow]) -> bool:
        return False

    def notify_always(self, rows: list[UsageRow]) -> None:
        pass

    def availability(self, rows: list[UsageRow]) -> list[ModelAvailability]:
        if any(row.is_exhausted for row in rows):
            return super().availability(rows)
        # A history estimate supplies no affirmative access/remaining signal.
        return []

    def fetch_raw(self) -> ProUsage:
        directory = self._get_cache_path().parent
        directory.chmod(0o700)
        with (directory / "ledger.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            client = ChatGPTClient(self.auth_path, directory / "cooldown.json")
            try:
                if _digest("chatgpt-pro", client.tokens.account_id) != self.account_id:
                    raise ValueError("ChatGPT account changed before collection")
                now = datetime.now(UTC)
                ledger_path = directory / "ledger.json"
                ledger = (
                    Ledger.model_validate_json(ledger_path.read_text())
                    if ledger_path.exists()
                    else Ledger(
                        account=self.account_id,
                        salt=secrets.token_hex(32),
                        observed_at=now,
                    )
                )
                if ledger.account != self.account_id:
                    raise ValueError("ChatGPT accounting ledger belongs to another account")
                init = InitResponse.model_validate(client.request("/backend-api/conversation/init", initialize=True))
                limits = [limit for limit in init.model_limits if limit.model_slug in PRO_MODELS and limit.resets_after > now]
                if limits:
                    ledger.server_reset = max(limit.resets_after for limit in limits)
                    ledger.last_blocked_at = now
                    ledger.first_unblocked_at = None
                elif ledger.last_blocked_at is not None and ledger.first_unblocked_at is None:
                    ledger.first_unblocked_at = now
                cutoff = now - WEEK
                if ledger.server_reset is not None and ledger.server_reset > now:
                    cutoff = min(cutoff, ledger.server_reset - WEEK)
                history_cutoff = max(cutoff, ledger.observed_at) if ledger.conversations else cutoff
                for item in client.history(history_cutoff).values():
                    key = _digest(ledger.salt, item.id)
                    if ledger.conversations.get(key) == item.update_time:
                        continue
                    conversation = Conversation.model_validate(client.request("/backend-api/conversation/" + quote(item.id, safe="")))
                    ledger.finals.update(extract_finals(conversation, item.id, ledger.salt))
                    ledger.conversations[key] = item.update_time
                ledger.observed_at = now
                _write_json_atomic(ledger_path, ledger.model_dump(mode="json"))
                ledger_path.chmod(0o600)
                return self.summarize(ledger, now, limit=settings.chatgpt_pro.weekly_limit)
            finally:
                client.close()

    def summarize(self, ledger: Ledger, now: datetime, *, limit: int) -> ProUsage:
        server_reset = ledger.server_reset
        anchored = server_reset is not None and server_reset > now
        end = server_reset if anchored else now
        assert end is not None
        start = end - WEEK
        finals = [final for final in ledger.finals.values() if start.timestamp() <= final.timestamp < end.timestamp()]
        interactions = len({final.group for final in finals})
        blocked = anchored and ledger.first_unblocked_at is None
        return {
            "interactions": interactions,
            "raw_finals": len(finals),
            "limit": limit,
            "remaining_min": 0 if blocked else max(0, limit - len(finals)),
            "remaining_max": 0 if blocked else max(0, limit - interactions),
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "window_basis": "server-reset-minus-seven-days" if anchored else "provisional-rolling-seven-days",
            "blocked": blocked,
            "server_reset": end.isoformat() if anchored else None,
            "observed_at": ledger.observed_at.isoformat(),
        }

    def to_rows(self, raw: ProUsage) -> list[UsageRow]:
        count = str(raw["interactions"]) if raw["interactions"] == raw["raw_finals"] else f"{raw['interactions']}–{raw['raw_finals']}"
        label = f"ChatGPT Pro weekly — {count} / {raw['limit']} messages · Estimated"
        reset = raw["server_reset"]
        return [
            ChatGPTProRow(
                identifier=label + (" · server blocked" if raw["blocked"] else ""),
                pct_used=100 if raw["blocked"] else round(100 * raw["interactions"] / raw["limit"]),
                server_blocked=raw["blocked"],
                reset_at=datetime.fromisoformat(reset) if reset is not None else None,
            )
        ]

    def metadata(self, raw: ProUsage, rows: list[UsageRow]) -> dict[str, JsonValue]:
        return {
            "accounting": cast(JsonValue, dict(raw)),
            "measurement": "history-derived message range",
            "limit_basis": "configured assumption",
            "coverage": "Retained active, archived and project history; deleted, temporary and unavailable chats may be absent.",
        }
