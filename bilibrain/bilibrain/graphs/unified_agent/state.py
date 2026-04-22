from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable, TypedDict

if TYPE_CHECKING:
    from bilibrain.core.runtime import Runtime


class UnifiedAgentState(TypedDict, total=False):
    conversation_id: int
    task_id: str
    assistant_message_id: int | None
    session_id: str
    workspace_id: str

    query: str
    folder_id: int | None
    bvid: str | None
    scope_mode: str | None
    scope: dict[str, Any]
    scope_description: str

    messages: list[Any]
    pending_tool_calls: list[dict[str, Any]]
    current_tool_call: dict[str, Any] | None
    current_tool_use_id: str | None
    current_tool_result: str | None

    collected_sources: list[dict[str, str]]
    pending_answer_text: str
    answer_text: str
    answer_mode: str | None
    route_mode: str | None

    status: str
    error: str | None
    context_snapshot: dict[str, Any]


class UnifiedAgentContext(TypedDict, total=False):
    runtime: Runtime
    actor: str
    approval_mode: Any
    stream: bool
    persisted_event_tasks: list[asyncio.Task[None]]
    downstream: Callable[[str, dict[str, Any]], None] | None
