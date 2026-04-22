from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, AsyncIterator

from bilibrain.services.chat_storage import (
    append_chat_message,
    list_chat_session_messages,
    replace_chat_message,
)
from bilibrain.services.context_usage import get_conversation_context_usage
from bilibrain.services.chat_memory import refresh_context_stats_after_message
from bilibrain.services.citations import normalize_answer_citations
from bilibrain.services.agent_common import (
    get_default_workspace,
    get_or_create_conversation,
)
from bilibrain.services.task_execution import mark_command_failed, mark_task_completed
from bilibrain.prompts import build_unified_agent_context_message, build_unified_agent_system_prompt
from bilibrain.skills import build_skill_langchain_tools
from bilibrain.tools import build_langchain_tools

if TYPE_CHECKING:
    from bilibrain.core.runtime import Runtime


_EPHEMERAL_ASSISTANT_TEXTS = {"", "正在思考...", "等待你审批后继续执行。"}


def _build_skills_state(runtime: Runtime, session_id: str) -> dict[str, Any]:
    if runtime.skill_service is None:
        return {"active_skills": [], "loaded_skills": []}
    return {
        "active_skills": runtime.skill_service.get_active_skills(session_id),
        "loaded_skills": runtime.skill_service.get_loaded_skills(session_id),
    }


def _strip_ephemeral_assistant_text(content: str | None) -> str:
    text = str(content or "")
    return "" if text in _EPHEMERAL_ASSISTANT_TEXTS else text


def _merge_assistant_message_text(existing_text: str | None, incoming_text: str | None) -> str:
    base = _strip_ephemeral_assistant_text(existing_text)
    tail = str(incoming_text or "")
    if not base:
        return tail
    if not tail:
        return base
    return f"{base}{tail}"


async def _read_assistant_message_text(
    runtime: Runtime,
    *,
    conversation_id: int,
    message_id: int | None,
) -> str:
    if message_id is None:
        return ""
    messages = await list_chat_session_messages(runtime, int(conversation_id))
    for item in messages:
        if int(item.get("message_id") or 0) == int(message_id):
            return str(item.get("content") or "")
    return ""


async def _persist_task_primary_message(
    runtime: Runtime,
    *,
    conversation_id: int,
    task_id: str | None,
    message_id: int | None,
    content: str,
    merge_with_existing: bool = False,
    sources: list[dict[str, Any]] | None = None,
    answer_mode: str | None = None,
    route_mode: str | None = None,
) -> tuple[dict[str, Any], str]:
    normalized = normalize_answer_citations(content)
    final_content = normalized
    if merge_with_existing:
        existing_text = await _read_assistant_message_text(
            runtime,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        final_content = _merge_assistant_message_text(existing_text, normalized)

    if message_id is not None:
        assistant_message = await replace_chat_message(
            runtime,
            conversation_id=conversation_id,
            message_id=message_id,
            content=final_content,
            task_id=task_id,
            message_kind="task_primary",
            sources=sources,
            answer_mode=answer_mode,
            route_mode=route_mode,
        )
    else:
        assistant_message = await append_chat_message(
            runtime,
            conversation_id,
            role="assistant",
            content=final_content,
            task_id=task_id,
            message_kind="task_primary",
            sources=sources or [],
            answer_mode=answer_mode,
            route_mode=route_mode,
        )
    return assistant_message, final_content


async def _flush_persisted_event_tasks(tasks: list[asyncio.Task[None]]) -> None:
    if not tasks:
        return
    pending = [task for task in tasks if not task.done()]
    if pending:
        await asyncio.gather(*pending)


def build_unified_session_id(
    *,
    conversation_id: int | None = None,
    explicit_session_id: str | None = None,
) -> str:
    explicit = str(explicit_session_id or "").strip()
    if explicit:
        return explicit
    if conversation_id:
        return f"conversation-{int(conversation_id)}"
    raise RuntimeError("session_id is required when conversation_id is not provided.")


def build_unified_agent_prompt(
    runtime: Runtime,
    *,
    session_id: str,
    workspace_id: str,
    scope_description: str,
    memory_text: str,
    actor: str,
) -> str:
    _ = (runtime, session_id, workspace_id, scope_description, memory_text, actor)
    return build_unified_agent_system_prompt()


def build_unified_agent_context_prompt(
    runtime: Runtime,
    *,
    session_id: str,
    workspace_id: str,
    scope_description: str,
    memory_text: str,
    actor: str,
) -> str:
    available_skills = (
        runtime.skill_service.build_available_skills_prompt(session_id=session_id, actor=actor)
        if runtime.skill_service
        else "<available_skills />"
    )
    return build_unified_agent_context_message(
        scope_description=scope_description,
        workspace_id=workspace_id,
        available_skills=available_skills,
        memory_text=memory_text,
    )


def _summarize_tool_args(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "run_command":
        return {"command": str(arguments.get("command") or ""), "cwd": str(arguments.get("cwd") or ".")}
    if tool_name == "web_search":
        return {"query": str(arguments.get("query") or "")}
    if tool_name in {"write_file", "append_file"}:
        content = str(arguments.get("content") or "")
        return {"path": str(arguments.get("path") or ""), "content_length": len(content)}
    if tool_name == "obsidian_write_note":
        content = str(arguments.get("content") or "")
        return {
            "path": str(arguments.get("path") or ""),
            "content_length": len(content),
            "overwrite": bool(arguments.get("overwrite", True)),
        }
    if tool_name == "obsidian_read_note":
        return {"path": str(arguments.get("path") or "")}
    if tool_name == "make_dir":
        return {"path": str(arguments.get("path") or "")}
    return {"path": str(arguments.get("path") or ".")} if tool_name in {"read_file", "list_dir"} else {}


async def _postprocess(
    runtime: Runtime,
    *,
    answer_text: str,
    sources: list[dict[str, str]],
    conversation_id: int,
    task_id: str | None = None,
    route_mode: str | None = None,
    placeholder_message_id: int | None = None,
) -> dict[str, Any]:
    normalized = normalize_answer_citations(answer_text)

    answer_mode = "chunk"
    if sources:
        first_source = sources[0]
        answer_mode = "summary" if first_source.get("source_kind") == "summary" else "chunk"

    if placeholder_message_id is not None:
        assistant_message = await replace_chat_message(
            runtime,
            conversation_id=conversation_id,
            message_id=placeholder_message_id,
            content=normalized,
            task_id=task_id,
            message_kind="task_primary",
            sources=sources,
            answer_mode=answer_mode,
            route_mode=route_mode,
        )
    else:
        assistant_message = await append_chat_message(
            runtime,
            conversation_id,
            "assistant",
            normalized,
            task_id=task_id,
            message_kind="task_primary",
            sources=sources,
            answer_mode=answer_mode,
            route_mode=route_mode,
        )
    await refresh_context_stats_after_message(
        runtime,
        conversation_id=conversation_id,
        message=assistant_message,
    )
    if task_id:
        await mark_task_completed(
            runtime,
            conversation_id=conversation_id,
            task_id=task_id,
            route_mode=route_mode,
            answer_mode=answer_mode,
        )

    return {
        "answer_text": normalized,
        "answer_mode": answer_mode,
        "assistant_message": assistant_message,
    }


def _resolve_conversation_id(
    session_id: str,
    conversation_id: int | None,
) -> int:
    normalized = int(conversation_id) if conversation_id else None
    if normalized is None and str(session_id).startswith("conversation-"):
        try:
            normalized = int(str(session_id).split("-", 1)[1])
        except ValueError:
            pass
    if normalized is None:
        raise RuntimeError("conversation_id is required to resume the agent.")
    return normalized


async def project_graph_pending_approval(
    runtime: Runtime,
    *,
    conversation_id: int,
    task_id: str | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    from bilibrain.services import unified_agent_graph_runtime as graph_runtime

    return await graph_runtime.project_graph_pending_approval(
        runtime,
        conversation_id=conversation_id,
        task_id=task_id,
        tasks=tasks,
    )


async def answer_with_unified_agent(
    runtime: Runtime,
    *,
    query: str,
    folder_id: int | None = None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
    session_id: str | None = None,
    approval_mode=None,
    actor: str = "agent",
) -> dict[str, Any]:
    _ = session_id
    from bilibrain.services import unified_agent_graph_runtime as graph_runtime

    return await graph_runtime.graph_invoke_unified_agent(
        runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        conversation_id=conversation_id,
        approval_mode=approval_mode,
        actor=actor,
    )


async def stream_unified_agent_events(
    runtime: Runtime,
    *,
    query: str,
    folder_id: int | None = None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
    session_id: str | None = None,
    approval_mode=None,
    actor: str = "agent",
) -> AsyncIterator[str]:
    _ = session_id
    from bilibrain.services import unified_agent_graph_runtime as graph_runtime

    async for item in graph_runtime.graph_stream_unified_agent_events(
        runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        conversation_id=conversation_id,
        approval_mode=approval_mode,
        actor=actor,
    ):
        yield item


async def resume_unified_agent_turn(
    runtime: Runtime,
    *,
    session_id: str,
    decision: dict[str, Any],
    conversation_id: int | None = None,
    task_id: str | None = None,
    folder_id: int | None = None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    actor: str = "agent",
) -> dict[str, Any]:
    _ = folder_id, bvid, scope_mode
    from bilibrain.services import unified_agent_graph_runtime as graph_runtime

    return await graph_runtime.graph_resume_unified_agent(
        runtime,
        session_id=session_id,
        decision=decision,
        conversation_id=conversation_id,
        task_id=task_id,
        actor=actor,
    )


async def stream_resume_unified_agent_events(
    runtime: Runtime,
    *,
    session_id: str,
    decision: dict[str, Any],
    conversation_id: int | None = None,
    task_id: str | None = None,
    folder_id: int | None = None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    actor: str = "agent",
) -> AsyncIterator[str]:
    _ = folder_id, bvid, scope_mode
    from bilibrain.services import unified_agent_graph_runtime as graph_runtime

    async for item in graph_runtime.graph_stream_resume_unified_agent_events(
        runtime,
        session_id=session_id,
        decision=decision,
        conversation_id=conversation_id,
        task_id=task_id,
        actor=actor,
    ):
        yield item
