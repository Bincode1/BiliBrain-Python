from __future__ import annotations

from typing import Any

from bilibrain.core.runtime import Runtime
from bilibrain.services.context_usage import get_conversation_context_usage
from bilibrain.services.chat_storage import (
    create_chat_session_dual_write,
    delete_chat_session_dual_write,
    ensure_all_chat_store_sessions_loaded,
    ensure_chat_store_session_loaded,
    list_chat_session_tool_events,
    read_chat_session_pending_approval,
    rename_chat_session_dual_write,
)


async def create_chat_conversation(
    runtime: Runtime,
    title: str | None = None,
) -> dict[str, Any]:
    conversation = await create_chat_session_dual_write(runtime, folder_id=None, title=title)
    return {
        "conversation": conversation,
        "messages": [],
    }


async def delete_chat_conversation(
    runtime: Runtime, conversation_id: int
) -> dict[str, Any]:
    conversation = await _get_chat_conversation(runtime, int(conversation_id))
    if not conversation:
        raise RuntimeError("对话会话不存在，请刷新页面后重试。")

    await delete_chat_session_dual_write(runtime, int(conversation_id))
    conversations = await _list_chat_conversations(runtime)
    next_active_id = conversations[0]["conversation_id"] if conversations else None
    return {
        "deleted_conversation_id": int(conversation_id),
        "active_conversation_id": next_active_id,
        "conversations": conversations,
    }


async def rename_chat_conversation(
    runtime: Runtime,
    conversation_id: int,
    title: str,
) -> dict[str, Any]:
    conversation = await rename_chat_session_dual_write(runtime, int(conversation_id), title)
    if not conversation:
        raise RuntimeError("对话会话不存在，请刷新页面后重试。")
    conversations = await _list_chat_conversations(runtime)
    return {
        "conversation": conversation,
        "conversations": conversations,
    }


async def get_chat_history(
    runtime: Runtime,
    conversation_id: int | None = None,
) -> dict[str, Any]:
    if conversation_id is None:
        conversations = await _list_chat_conversations(runtime)
        conversation = conversations[0] if conversations else None
        if not conversation:
            return {
                "conversation_id": None,
                "folder_id": None,
                "title": "",
                "messages": [],
                "tool_events": [],
            }
    else:
        conversation = await _get_chat_conversation(runtime, int(conversation_id))
        if not conversation:
            raise RuntimeError("对话会话不存在，请刷新页面后重试。")

    resolved_id = conversation["conversation_id"]
    messages = await _list_chat_messages(runtime, resolved_id)
    pending_approval = await read_chat_session_pending_approval(runtime, resolved_id)

    tool_events = await list_chat_session_tool_events(runtime, resolved_id)
    if tool_events:
        _attach_persisted_events_to_messages(messages, tool_events)

    if runtime.skill_service is not None:
        session_id = f"conversation-{resolved_id}"
        loaded_skills = runtime.skill_service.get_loaded_skills(session_id)
        if loaded_skills:
            _attach_loaded_skills_to_messages(messages, loaded_skills)

    return {
        "conversation_id": resolved_id,
        "folder_id": conversation.get("folder_id"),
        "title": conversation.get("title") or "",
        "messages": messages,
        "pending_approval": pending_approval,
        "context_usage": await get_conversation_context_usage(runtime, resolved_id),
    }


def _attach_persisted_events_to_messages(
    messages: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    if not events or not messages:
        return

    for event in events:
        event_type = str(event.get("event_type") or "").strip().lower()
        if event_type not in {"tool", "skill"}:
            continue
        target_idx = _find_following_assistant_index(messages, event.get("created_at"))
        if target_idx is None:
            target_idx = _find_preceding_assistant_index(messages, event.get("created_at"))
        if target_idx is None:
            continue
        msg = messages[target_idx]
        field_name = "tool_events" if event_type == "tool" else "skill_events"
        if field_name not in msg or not isinstance(msg.get(field_name), list):
            msg[field_name] = []
        summary = {
            key: value
            for key, value in event.items()
            if key not in {"event_type"}
        }
        msg[field_name].append(summary)


def _find_preceding_assistant_index(
    messages: list[dict[str, Any]], started_at: str | None
) -> int | None:
    """Find the index of the last assistant message at or before started_at."""
    if not started_at:
        # Fallback: return last assistant message
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "assistant":
                return i
        return None

    best = None
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        msg_time = msg.get("created_at") or ""
        if msg_time and msg_time <= started_at:
            best = i
    if best is None:
        # If no assistant message matches by time, attach to the last one
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "assistant":
                return i
    return best


def _find_following_assistant_index(
    messages: list[dict[str, Any]], started_at: str | None
) -> int | None:
    if not started_at:
        return None
    for index, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        msg_time = msg.get("created_at") or ""
        if msg_time and msg_time >= started_at:
            return index
    return None


def _attach_loaded_skills_to_messages(
    messages: list[dict[str, Any]],
    loaded_skills: list[dict[str, Any]],
) -> None:
    if not messages or not loaded_skills:
        return
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") != "assistant":
            continue
        if "loaded_skills" not in messages[index] or not isinstance(messages[index].get("loaded_skills"), list):
            messages[index]["loaded_skills"] = []
        messages[index]["loaded_skills"].extend(loaded_skills)
        return


async def list_chat_conversations(runtime: Runtime) -> dict[str, Any]:
    conversations = await _list_chat_conversations(runtime)
    latest = conversations[0]["conversation_id"] if conversations else None
    return {
        "folder_id": None,
        "active_conversation_id": latest,
        "conversations": conversations,
    }


async def _list_chat_conversations(runtime: Runtime) -> list[dict[str, Any]]:
    chat_store = runtime.require_chat_store() if hasattr(runtime, "require_chat_store") else runtime.chat_store
    await ensure_all_chat_store_sessions_loaded(runtime)
    return await chat_store.list_sessions()


async def _get_chat_conversation(
    runtime: Runtime, conversation_id: int
) -> dict[str, Any] | None:
    chat_store = runtime.require_chat_store() if hasattr(runtime, "require_chat_store") else runtime.chat_store
    await ensure_chat_store_session_loaded(runtime, int(conversation_id))
    return await chat_store.get_session(int(conversation_id))


async def _list_chat_messages(
    runtime: Runtime, conversation_id: int
) -> list[dict[str, Any]]:
    chat_store = runtime.require_chat_store() if hasattr(runtime, "require_chat_store") else runtime.chat_store
    await ensure_chat_store_session_loaded(runtime, int(conversation_id))
    return await chat_store.list_messages(int(conversation_id))
