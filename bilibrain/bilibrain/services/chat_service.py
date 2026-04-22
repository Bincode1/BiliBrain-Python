from __future__ import annotations

from typing import Any

from bilibrain.core.runtime import Runtime
from bilibrain.services.context_usage import get_conversation_context_usage
from bilibrain.services.chat_storage import (
    create_chat_session,
    delete_chat_session,
    get_chat_session,
    list_chat_session_approvals,
    list_chat_session_task_events,
    list_chat_session_tasks,
    list_chat_session_tool_uses,
    rename_chat_session,
)


async def create_chat_conversation(
    runtime: Runtime,
    title: str | None = None,
) -> dict[str, Any]:
    conversation = await create_chat_session(runtime, folder_id=None, title=title)
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

    await delete_chat_session(runtime, int(conversation_id))
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
    conversation = await rename_chat_session(runtime, int(conversation_id), title)
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
    tasks = await list_chat_session_tasks(runtime, resolved_id)
    tool_uses = await list_chat_session_tool_uses(runtime, resolved_id)
    approvals = await list_chat_session_approvals(runtime, resolved_id)
    task_events = await list_chat_session_task_events(runtime, resolved_id)
    from bilibrain.services.unified_agent import project_graph_pending_approval

    pending_approval = await project_graph_pending_approval(
        runtime,
        conversation_id=resolved_id,
        tasks=tasks,
    )

    return {
        "conversation_id": resolved_id,
        "folder_id": conversation.get("folder_id"),
        "title": conversation.get("title") or "",
        "messages": messages,
        "tasks": tasks,
        "tool_uses": tool_uses,
        "approvals": approvals,
        "task_events": task_events,
        "pending_approval": pending_approval,
        "context_usage": await get_conversation_context_usage(runtime, resolved_id),
    }


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
    return await chat_store.list_sessions()


async def _get_chat_conversation(
    runtime: Runtime, conversation_id: int
) -> dict[str, Any] | None:
    return await get_chat_session(runtime, int(conversation_id))


async def _list_chat_messages(
    runtime: Runtime, conversation_id: int
) -> list[dict[str, Any]]:
    chat_store = runtime.require_chat_store() if hasattr(runtime, "require_chat_store") else runtime.chat_store
    return await chat_store.list_messages(int(conversation_id))
