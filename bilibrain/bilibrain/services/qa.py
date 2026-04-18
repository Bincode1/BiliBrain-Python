from __future__ import annotations

from typing import Any

from bilibrain.core.runtime import Runtime


async def create_chat_conversation(
    runtime: Runtime,
    title: str | None = None,
) -> dict[str, Any]:
    conversation = await runtime.db.create_chat_conversation(None, title=title)
    return {
        "conversation": conversation,
        "messages": [],
    }


async def delete_chat_conversation(
    runtime: Runtime, conversation_id: int
) -> dict[str, Any]:
    conversation = await runtime.db.get_chat_conversation(int(conversation_id))
    if not conversation:
        raise RuntimeError("对话会话不存在，请刷新页面后重试。")

    await runtime.db.delete_chat_conversation(int(conversation_id))
    conversations = await runtime.db.list_chat_conversations(None, all_scopes=True)
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
    conversation = await runtime.db.rename_chat_conversation(
        int(conversation_id), title
    )
    if not conversation:
        raise RuntimeError("对话会话不存在，请刷新页面后重试。")
    conversations = await runtime.db.list_chat_conversations(None, all_scopes=True)
    return {
        "conversation": conversation,
        "conversations": conversations,
    }


async def get_chat_history(
    runtime: Runtime,
    conversation_id: int | None = None,
) -> dict[str, Any]:
    if conversation_id is None:
        conversation = await runtime.db.get_latest_chat_conversation(
            None, all_scopes=True
        )
        if not conversation:
            return {
                "conversation_id": None,
                "folder_id": None,
                "title": "",
                "messages": [],
                "tool_events": [],
            }
    else:
        conversation = await runtime.db.get_chat_conversation(int(conversation_id))
        if not conversation:
            raise RuntimeError("对话会话不存在，请刷新页面后重试。")

    resolved_id = conversation["conversation_id"]
    messages = await runtime.db.list_chat_messages(resolved_id)

    # Load persisted tool calls and attach to their preceding assistant message
    tool_calls = await runtime.db.list_tool_calls_for_conversation(resolved_id)
    if tool_calls:
        # Build a list of (message_index, tool_events) by matching tool call
        # started_at to the nearest preceding assistant message.
        _attach_tool_events_to_messages(messages, tool_calls)

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
    }


def _attach_tool_events_to_messages(
    messages: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> None:
    """Attach tool_calls as tool_events on the nearest preceding assistant message."""
    if not tool_calls or not messages:
        return

    # Build lightweight summary for each tool call, matching the shape
    # emitted during SSE streaming so the frontend can render them identically.
    for tc in tool_calls:
        summary = _summarize_tool_call(tc)
        # Find the nearest assistant message whose created_at <= tc.started_at
        target_idx = _find_preceding_assistant_index(messages, tc.get("started_at"))
        if target_idx is not None:
            msg = messages[target_idx]
            if "tool_events" not in msg or not isinstance(msg.get("tool_events"), list):
                msg["tool_events"] = []
            msg["tool_events"].append(summary)


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


def _summarize_tool_call(tc: dict[str, Any]) -> dict[str, Any]:
    """Build a tool event summary from a tool_call row, matching SSE shape."""
    args = tc.get("arguments") or {}
    result = tc.get("result")
    name = tc.get("tool_name") or ""
    ok = tc.get("status") == "finished"
    error = tc.get("error")

    summary: dict[str, Any] = {"name": name}

    # Summarize args per tool (mirrors langchain_tools._summarize_tool_args)
    if name == "run_command":
        summary["command"] = str(args.get("command") or "")
        summary["cwd"] = str(args.get("cwd") or ".")
    elif name == "web_search":
        summary["query"] = str(args.get("query") or "")
    elif name in ("write_file", "append_file"):
        content = str(args.get("content") or "")
        summary["path"] = str(args.get("path") or "")
        summary["content_length"] = len(content)
    elif name == "make_dir":
        summary["path"] = str(args.get("path") or "")
    elif name in ("read_file", "list_dir"):
        summary["path"] = str(args.get("path") or ".")
    elif name in ("search_knowledge_base", "search_video_summaries"):
        summary["query"] = str(args.get("query") or "")

    if result is not None:
        summary["ok"] = ok
    if error:
        summary["error"] = str(error)
    summary["duration_ms"] = tc.get("duration_ms", 0)
    summary["phase"] = "finish" if tc.get("status") in ("finished", "failed") else "start"

    return summary


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
    conversations = await runtime.db.list_chat_conversations(None, all_scopes=True)
    latest = conversations[0]["conversation_id"] if conversations else None
    return {
        "folder_id": None,
        "active_conversation_id": latest,
        "conversations": conversations,
    }
