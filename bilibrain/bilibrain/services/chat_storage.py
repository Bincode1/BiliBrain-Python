from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from uuid import uuid4


_CHAT_ID_LOCK = asyncio.Lock()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _conversation_scope_key(folder_id: int | None) -> str:
    scope_prefix = f"folder:{int(folder_id)}" if folder_id else "all"
    return f"{scope_prefix}:{uuid4().hex[:16]}"


async def _next_conversation_id(chat_store) -> int:
    sessions = await chat_store.list_sessions()
    max_id = max((int(item.get("conversation_id") or 0) for item in sessions), default=0)
    return max_id + 1


async def _next_message_id(chat_store) -> int:
    max_id = 0
    for session in await chat_store.list_sessions():
        conversation_id = int(session.get("conversation_id") or 0)
        for message in await chat_store.list_messages(conversation_id):
            max_id = max(max_id, int(message.get("message_id") or 0))
    return max_id + 1


def _require_chat_store(runtime):
    chat_store = getattr(runtime, "chat_store", None)
    if chat_store is None:
        require_chat_store = getattr(runtime, "require_chat_store", None)
        if callable(require_chat_store):
            return require_chat_store()
        raise RuntimeError("Chat store is not initialized.")
    return chat_store


async def get_chat_session(runtime, conversation_id: int) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.get_session(normalized_id)


async def list_chat_session_messages(
    runtime, conversation_id: int
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_messages(normalized_id)


async def list_recent_chat_session_messages(
    runtime,
    conversation_id: int,
    *,
    keep_turns: int,
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_recent_messages_by_turns(
        normalized_id,
        keep_turns=keep_turns,
    )


async def list_chat_session_messages_between(
    runtime,
    conversation_id: int,
    *,
    start_message_id: int | None = None,
    end_message_id: int | None = None,
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_messages_between(
        normalized_id,
        start_message_id=start_message_id,
        end_message_id=end_message_id,
    )


async def list_chat_session_tasks(
    runtime,
    conversation_id: int,
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_tasks(normalized_id)


async def get_chat_session_task(
    runtime,
    conversation_id: int,
    task_id: str,
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.get_task(normalized_id, task_id)


async def list_chat_session_tool_uses(
    runtime,
    conversation_id: int,
    *,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_tool_uses(normalized_id, task_id=task_id)


async def get_chat_session_tool_use(
    runtime,
    conversation_id: int,
    tool_use_id: str,
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.get_tool_use(normalized_id, tool_use_id)


async def list_chat_session_approvals(
    runtime,
    conversation_id: int,
    *,
    task_id: str | None = None,
    tool_use_id: str | None = None,
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_approvals(
        normalized_id,
        task_id=task_id,
        tool_use_id=tool_use_id,
    )


async def get_chat_session_approval(
    runtime,
    conversation_id: int,
    approval_id: str,
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.get_approval(normalized_id, approval_id)


async def list_chat_session_task_events(
    runtime,
    conversation_id: int,
    *,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_task_events(normalized_id, task_id=task_id)


async def read_chat_session_memory(
    runtime, conversation_id: int
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.read_memory(normalized_id)


async def read_chat_session_context_stats(
    runtime, conversation_id: int
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.read_context_stats(normalized_id)


async def list_chat_session_tool_events(
    runtime, conversation_id: int
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_tool_events(normalized_id)


async def ensure_chat_session(
    runtime,
    *,
    conversation_id: int | None,
    folder_id: int | None,
    title: str | None = None,
) -> dict[str, Any] | None:
    if conversation_id is None:
        return await create_chat_session(runtime, folder_id=folder_id, title=title)
    return await get_chat_session(runtime, int(conversation_id))


async def create_chat_session(
    runtime,
    *,
    folder_id: int | None,
    title: str | None = None,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    async with _CHAT_ID_LOCK:
        conversation_id = await _next_conversation_id(chat_store)
        now = _now_text()
        return await chat_store.create_session(
            conversation_id,
            title=title or "",
            folder_id=folder_id,
            scope_key=_conversation_scope_key(folder_id),
            created_at=now,
            updated_at=now,
        )


async def rename_chat_session(
    runtime,
    conversation_id: int,
    title: str,
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    return await chat_store.rename_session(int(conversation_id), title)


async def delete_chat_session(runtime, conversation_id: int) -> bool:
    chat_store = _require_chat_store(runtime)
    return await chat_store.delete_session(int(conversation_id))


async def append_chat_message(
    runtime,
    conversation_id: int,
    role: str,
    content: str,
    *,
    task_id: str | None = None,
    sources: list[dict[str, Any]] | None = None,
    message_kind: str = "default",
    answer_mode: str | None = None,
    route_mode: str | None = None,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    async with _CHAT_ID_LOCK:
        message_id = await _next_message_id(chat_store)
        now = _now_text()
        return await chat_store.append_message(
            int(conversation_id),
            role=role,
            content=content,
            task_id=task_id,
            sources=sources or [],
            message_kind=message_kind,
            answer_mode=answer_mode,
            route_mode=route_mode,
            message_id=message_id,
            created_at=now,
            updated_at=now,
        )


async def replace_chat_message(
    runtime,
    *,
    conversation_id: int,
    message_id: int,
    content: str | None = None,
    task_id: str | None = None,
    sources: list[dict[str, Any]] | None = None,
    message_kind: str | None = None,
    answer_mode: str | None = None,
    route_mode: str | None = None,
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    return await chat_store.replace_message(
        int(message_id),
        conversation_id=int(conversation_id),
        content=content,
        task_id=task_id,
        sources=sources,
        message_kind=message_kind,
        answer_mode=answer_mode,
        route_mode=route_mode,
    )


async def write_chat_memory(
    runtime,
    conversation_id: int,
    *,
    memory_text: str,
    compacted_until_message_id: int | None,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    return await chat_store.write_memory(
        int(conversation_id),
        memory_text=memory_text,
        compacted_until_message_id=compacted_until_message_id,
    )


async def write_context_stats(
    runtime,
    conversation_id: int,
    *,
    last_message_id: int | None,
    compacted_until_message_id: int | None,
    recent_start_message_id: int | None,
    memory_token_estimate: int,
    uncompacted_token_estimate: int,
    recent_token_estimate: int,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    return await chat_store.write_context_stats(
        int(conversation_id),
        last_message_id=last_message_id,
        compacted_until_message_id=compacted_until_message_id,
        recent_start_message_id=recent_start_message_id,
        memory_token_estimate=memory_token_estimate,
        uncompacted_token_estimate=uncompacted_token_estimate,
        recent_token_estimate=recent_token_estimate,
    )


async def append_chat_tool_event(
    runtime,
    conversation_id: int,
    *,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    chat_store = _require_chat_store(runtime)
    event_payload = dict(payload or {})
    event_payload["event_type"] = str(event_type or "").strip().lower()
    await chat_store.append_tool_event(int(conversation_id), event_payload)


async def append_chat_task(
    runtime,
    conversation_id: int,
    *,
    task_id: str,
    user_message_id: int | None = None,
    assistant_message_id: int | None = None,
    status: str = "queued",
    phase: str = "preparing",
    route_mode: str | None = None,
    answer_mode: str | None = None,
    pending_tool_use_id: str | None = None,
    retry_count: int = 0,
    failure_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    now = _now_text()
    return await chat_store.append_task(
        int(conversation_id),
        task_id=task_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        status=status,
        phase=phase,
        route_mode=route_mode,
        answer_mode=answer_mode,
        pending_tool_use_id=pending_tool_use_id,
        retry_count=retry_count,
        failure_reason=failure_reason,
        created_at=now,
        updated_at=now,
        metadata=metadata or {},
    )


async def replace_chat_task(
    runtime,
    conversation_id: int,
    *,
    task_id: str,
    user_message_id: int | None = None,
    assistant_message_id: int | None = None,
    status: str | None = None,
    phase: str | None = None,
    route_mode: str | None = None,
    answer_mode: str | None = None,
    pending_tool_use_id: str | None = None,
    retry_count: int | None = None,
    failure_reason: str | None = None,
    completed_at: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    return await chat_store.replace_task(
        int(conversation_id),
        task_id=task_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        status=status,
        phase=phase,
        route_mode=route_mode,
        answer_mode=answer_mode,
        pending_tool_use_id=pending_tool_use_id,
        retry_count=retry_count,
        failure_reason=failure_reason,
        completed_at=completed_at,
        metadata=metadata,
    )


async def append_chat_tool_use(
    runtime,
    conversation_id: int,
    *,
    tool_use_id: str,
    task_id: str,
    tool_name: str,
    status: str = "pending",
    input_summary: dict[str, Any] | None = None,
    raw_input: dict[str, Any] | None = None,
    raw_output: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    request_id: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    now = _now_text()
    return await chat_store.append_tool_use(
        int(conversation_id),
        tool_use_id=tool_use_id,
        task_id=task_id,
        tool_name=tool_name,
        status=status,
        input_summary=input_summary or {},
        raw_input=raw_input or {},
        raw_output=raw_output,
        error=error,
        request_id=request_id,
        started_at=now,
        finished_at=finished_at,
        updated_at=now,
    )


async def replace_chat_tool_use(
    runtime,
    conversation_id: int,
    *,
    tool_use_id: str,
    status: str | None = None,
    input_summary: dict[str, Any] | None = None,
    raw_input: dict[str, Any] | None = None,
    raw_output: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    request_id: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    return await chat_store.replace_tool_use(
        int(conversation_id),
        tool_use_id=tool_use_id,
        status=status,
        input_summary=input_summary,
        raw_input=raw_input,
        raw_output=raw_output,
        error=error,
        request_id=request_id,
        finished_at=finished_at,
    )


async def append_chat_approval(
    runtime,
    conversation_id: int,
    *,
    approval_id: str,
    task_id: str,
    tool_use_id: str,
    status: str = "pending",
    request_payload: dict[str, Any] | None = None,
    decision_payload: dict[str, Any] | None = None,
    resolved_at: str | None = None,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    now = _now_text()
    return await chat_store.append_approval(
        int(conversation_id),
        approval_id=approval_id,
        task_id=task_id,
        tool_use_id=tool_use_id,
        status=status,
        request_payload=request_payload or {},
        decision_payload=decision_payload,
        created_at=now,
        resolved_at=resolved_at,
        updated_at=now,
    )


async def replace_chat_approval(
    runtime,
    conversation_id: int,
    *,
    approval_id: str,
    status: str | None = None,
    decision_payload: dict[str, Any] | None = None,
    resolved_at: str | None = None,
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    return await chat_store.replace_approval(
        int(conversation_id),
        approval_id=approval_id,
        status=status,
        decision_payload=decision_payload,
        resolved_at=resolved_at,
    )


async def append_chat_task_event(
    runtime,
    conversation_id: int,
    *,
    event_id: str,
    task_id: str,
    event_type: str,
    tool_use_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    return await chat_store.append_task_event(
        int(conversation_id),
        event_id=event_id,
        task_id=task_id,
        event_type=event_type,
        tool_use_id=tool_use_id,
        payload=payload or {},
        created_at=_now_text(),
    )
