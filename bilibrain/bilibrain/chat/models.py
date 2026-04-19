from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class ChatSessionMeta:
    conversation_id: int
    scope_key: str
    folder_id: int | None
    title: str
    message_count: int
    created_at: str | None
    updated_at: str | None
    status: str = "active"
    session_dirname: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChatMessageRecord:
    message_id: int
    conversation_id: int
    role: str
    content: str
    sources: list[dict[str, Any]]
    created_at: str | None
    answer_mode: str | None = None
    route_mode: str | None = None
    updated_at: str | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChatContextStats:
    conversation_id: int
    last_message_id: int | None
    compacted_until_message_id: int | None
    recent_start_message_id: int | None
    memory_token_estimate: int
    uncompacted_token_estimate: int
    recent_token_estimate: int
    updated_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChatIndexEntry:
    conversation_id: int
    scope_key: str
    folder_id: int | None
    title: str
    message_count: int
    created_at: str | None
    updated_at: str | None
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
