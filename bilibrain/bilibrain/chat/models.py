from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
    task_id: str | None
    role: str
    content: str
    sources: list[dict[str, Any]]
    created_at: str | None
    message_kind: str = "default"
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


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    conversation_id: int
    user_message_id: int | None
    assistant_message_id: int | None
    status: str
    phase: str
    route_mode: str | None = None
    answer_mode: str | None = None
    pending_tool_use_id: str | None = None
    retry_count: int = 0
    failure_reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolUseRecord:
    tool_use_id: str
    task_id: str
    tool_name: str
    status: str
    input_summary: dict[str, Any] = field(default_factory=dict)
    raw_input: dict[str, Any] = field(default_factory=dict)
    raw_output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    request_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ApprovalRecord:
    approval_id: str
    task_id: str
    tool_use_id: str
    status: str
    request_payload: dict[str, Any] = field(default_factory=dict)
    decision_payload: dict[str, Any] | None = None
    created_at: str | None = None
    resolved_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TaskEventRecord:
    event_id: str
    task_id: str
    tool_use_id: str | None
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
