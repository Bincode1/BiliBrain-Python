from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, AsyncIterator

from bilibrain.services.sse import make_sse_event
from langgraph.types import Command
from bilibrain.services.agent_common import format_interrupt as _format_interrupt
from bilibrain.services.chat_storage import (
    list_chat_session_approvals,
    list_chat_session_tasks,
)
from bilibrain.services.chat_memory import refresh_context_stats_after_message
from bilibrain.services.runtime_events import clear_pending_approval_state
from bilibrain.services.runtime_state import set_pending_approval_state
from bilibrain.services.task_execution import (
    create_task_shell,
    ensure_task_assistant_placeholder,
    mark_task_requires_action,
)
from bilibrain.services import unified_agent as shared

if TYPE_CHECKING:
    from bilibrain.core.runtime import Runtime


def _project_custom_stream_event(payload: dict[str, Any]) -> str | None:
    event_type = str(payload.get("event_type") or "").strip()
    if not event_type:
        return None
    event_data = payload.get("data") or {}
    if not isinstance(event_data, dict):
        event_data = {"value": event_data}
    if event_type == "answer_token":
        return make_sse_event("answer", {"delta": str(event_data.get("delta") or "")})
    return make_sse_event(event_type, event_data)


async def _find_pending_approval_id(
    runtime: Runtime,
    *,
    conversation_id: int,
    task_id: str,
    tool_use_id: str | None = None,
) -> str | None:
    approvals = await list_chat_session_approvals(
        runtime,
        int(conversation_id),
        task_id=task_id,
        tool_use_id=tool_use_id,
    )
    candidates = [
        item
        for item in approvals
        if str(item.get("status") or "").strip().lower() == "pending"
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
    )
    return str(candidates[-1].get("approval_id") or "").strip() or None


async def project_graph_pending_approval(
    runtime: Runtime,
    *,
    conversation_id: int,
    task_id: str | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    graph = getattr(runtime, "unified_agent_graph", None)
    if graph is None:
        return None

    candidate_task_ids: list[str] = []
    normalized_task_id = str(task_id or "").strip()
    if normalized_task_id:
        candidate_task_ids.append(normalized_task_id)

    task_rows = tasks
    if task_rows is None:
        task_rows = await list_chat_session_tasks(runtime, int(conversation_id))
    for item in task_rows or []:
        if str(item.get("status") or "").strip().lower() != "requires_action":
            continue
        current_task_id = str(item.get("task_id") or "").strip()
        if current_task_id and current_task_id not in candidate_task_ids:
            candidate_task_ids.append(current_task_id)

    for current_task_id in candidate_task_ids:
        config = {"configurable": {"thread_id": f"task-{current_task_id}"}}
        try:
            snapshot = await graph.aget_state(config)
        except Exception:
            continue
        interrupts = list(getattr(snapshot, "interrupts", ()) or ())
        if not interrupts:
            continue
        state_values = dict(getattr(snapshot, "values", {}) or {})
        interrupt = interrupts[0]
        approval_request = _format_interrupt(runtime, interrupt)
        current_tool_call = dict(state_values.get("current_tool_call") or {})
        tool_use_id = str(
            current_tool_call.get("id")
            or state_values.get("current_tool_use_id")
            or approval_request.get("interrupt_id")
            or ""
        ).strip()
        approval_id = await _find_pending_approval_id(
            runtime,
            conversation_id=int(conversation_id),
            task_id=current_task_id,
            tool_use_id=tool_use_id or None,
        )
        return {
            "conversation_id": int(conversation_id),
            "session_id": str(
                state_values.get("session_id")
                or shared.build_unified_session_id(conversation_id=int(conversation_id))
            ),
            "workspace_id": str(state_values.get("workspace_id") or "default"),
            "task_id": current_task_id,
            "tool_use_id": tool_use_id or None,
            "approval_id": approval_id,
            "assistant_message_id": int(state_values.get("assistant_message_id") or 0) or None,
            "approval_request": approval_request,
            "updated_at": str(getattr(snapshot, "created_at", "") or ""),
        }

    return None


async def prepare_graph_task_shell(
    runtime: Runtime,
    *,
    query: str,
    conversation_id: int | None,
    actor: str,
) -> dict[str, Any]:
    conversation = await shared.get_or_create_conversation(runtime, conversation_id)
    resolved_conversation_id = int(conversation["conversation_id"])
    task_shell = await create_task_shell(
        runtime,
        conversation_id=resolved_conversation_id,
        query=query,
    )
    user_message = task_shell["user_message"]
    await refresh_context_stats_after_message(
        runtime,
        conversation_id=resolved_conversation_id,
        message=user_message,
    )
    task = await ensure_task_assistant_placeholder(
        runtime,
        conversation_id=resolved_conversation_id,
        task_id=task_shell["task_id"],
    )
    workspace = await shared.get_default_workspace(runtime, actor=actor)
    workspace_id = str(workspace.get("workspace_id") or "default").strip() or "default"
    session_id = shared.build_unified_session_id(conversation_id=resolved_conversation_id)
    return {
        "conversation_id": resolved_conversation_id,
        "task_id": str(task_shell["task_id"]),
        "user_message_id": int(user_message["message_id"]),
        "assistant_message_id": int(task.get("assistant_message_id") or 0) or None,
        "workspace_id": workspace_id,
        "session_id": session_id,
    }


async def graph_invoke_unified_agent(
    runtime: Runtime,
    *,
    query: str,
    folder_id: int | None,
    bvid: str | None,
    scope_mode: str | None,
    conversation_id: int | None,
    approval_mode,
    actor: str,
) -> dict[str, Any]:
    graph = getattr(runtime, "unified_agent_graph", None)
    if graph is None:
        raise RuntimeError("Unified agent graph is not initialized.")

    persisted_event_tasks: list[asyncio.Task[None]] = []
    shell = await prepare_graph_task_shell(
        runtime,
        query=query,
        conversation_id=conversation_id,
        actor=actor,
    )
    config = {"configurable": {"thread_id": f"task-{shell['task_id']}"}}
    context = {
        "runtime": runtime,
        "actor": actor,
        "approval_mode": approval_mode,
        "stream": False,
        "persisted_event_tasks": persisted_event_tasks,
    }
    input_state = {
        "conversation_id": shell["conversation_id"],
        "task_id": shell["task_id"],
        "assistant_message_id": shell["assistant_message_id"],
        "session_id": shell["session_id"],
        "workspace_id": shell["workspace_id"],
        "query": query,
        "folder_id": folder_id,
        "bvid": bvid,
        "scope_mode": scope_mode,
    }

    try:
        result = await graph.ainvoke(input_state, config, context=context)
        if isinstance(result, dict) and result.get("__interrupt__"):
            interrupt = result["__interrupt__"][0]
            approval_request = _format_interrupt(runtime, interrupt)
            snapshot = await graph.aget_state(config)
            state_values = dict(getattr(snapshot, "values", {}) or {})
            pending_text = str(state_values.get("pending_answer_text") or "").strip()
            if pending_text:
                await shared._persist_task_primary_message(
                    runtime,
                    conversation_id=shell["conversation_id"],
                    task_id=shell["task_id"],
                    message_id=shell["assistant_message_id"],
                    content=pending_text,
                    merge_with_existing=True,
                )
            approval = await mark_task_requires_action(
                runtime,
                conversation_id=shell["conversation_id"],
                task_id=shell["task_id"],
                tool_use_id=str(approval_request.get("interrupt_id") or ""),
                approval_request=approval_request,
                session_id=shell["session_id"],
                workspace_id=shell["workspace_id"],
            )
            await set_pending_approval_state(
                runtime,
                exists=True,
                conversation_id=int(shell["conversation_id"]),
                workspace_id=str(shell["workspace_id"] or "default"),
                action_name=str((approval_request.get("action_requests") or [{}])[0].get("name") or "").strip() or None,
            )
            return {
                "status": "pending_approval",
                "conversation_id": shell["conversation_id"],
                "session_id": shell["session_id"],
                "workspace_id": shell["workspace_id"],
                "task_id": shell["task_id"],
                "tool_use_id": str(approval_request.get("interrupt_id") or ""),
                "approval_id": approval.get("approval_id"),
                "assistant_message_id": shell["assistant_message_id"],
                "approval_request": approval_request,
                **shared._build_skills_state(runtime, shell["session_id"]),
            }

        result = dict(result or {})
        if result.get("status") == "failed":
            raise RuntimeError(str(result.get("error") or "Unified agent graph 执行失败"))
        await clear_pending_approval_state(
            runtime,
            conversation_id=shell["conversation_id"],
            workspace_id=shell["workspace_id"],
        )
        return {
            "status": "completed",
            "conversation_id": shell["conversation_id"],
            "session_id": shell["session_id"],
            "workspace_id": shell["workspace_id"],
            "answer": str(result.get("answer_text") or ""),
            "answer_mode": result.get("answer_mode"),
            "assistant_message": (
                await shared._read_assistant_message_text(
                    runtime,
                    conversation_id=shell["conversation_id"],
                    message_id=shell["assistant_message_id"],
                )
            ),
            **shared._build_skills_state(runtime, shell["session_id"]),
        }
    finally:
        await shared._flush_persisted_event_tasks(persisted_event_tasks)


async def graph_stream_unified_agent_events(
    runtime: Runtime,
    *,
    query: str,
    folder_id: int | None,
    bvid: str | None,
    scope_mode: str | None,
    conversation_id: int | None,
    approval_mode,
    actor: str,
) -> AsyncIterator[str]:
    graph = getattr(runtime, "unified_agent_graph", None)
    if graph is None:
        raise RuntimeError("Unified agent graph is not initialized.")

    persisted_event_tasks: list[asyncio.Task[None]] = []
    shell = await prepare_graph_task_shell(
        runtime,
        query=query,
        conversation_id=conversation_id,
        actor=actor,
    )
    config = {"configurable": {"thread_id": f"task-{shell['task_id']}"}}
    context = {
        "runtime": runtime,
        "actor": actor,
        "approval_mode": approval_mode,
        "stream": True,
        "persisted_event_tasks": persisted_event_tasks,
    }
    input_state = {
        "conversation_id": shell["conversation_id"],
        "task_id": shell["task_id"],
        "assistant_message_id": shell["assistant_message_id"],
        "session_id": shell["session_id"],
        "workspace_id": shell["workspace_id"],
        "query": query,
        "folder_id": folder_id,
        "bvid": bvid,
        "scope_mode": scope_mode,
    }

    yield make_sse_event("conversation", {"conversation_id": shell["conversation_id"]})
    yield make_sse_event(
        "task",
        {"task_id": shell["task_id"], "assistant_message_id": shell["assistant_message_id"]},
    )
    yield make_sse_event(
        "task_status",
        {
            "task_id": shell["task_id"],
            "assistant_message_id": shell["assistant_message_id"],
            "status": "running",
            "phase": "running",
        },
    )

    captured_interrupt = None
    try:
        async for chunk in graph.astream(
            input_state,
            config,
            context=context,
            stream_mode=["custom", "updates"],
            version="v2",
        ):
            chunk_type = chunk.get("type")
            if chunk_type == "custom":
                payload = dict(chunk.get("data") or {})
                projected = _project_custom_stream_event(payload)
                if projected is not None:
                    yield projected
            elif chunk_type == "updates":
                data = dict(chunk.get("data") or {})
                interrupts = data.get("__interrupt__")
                if interrupts:
                    captured_interrupt = interrupts[0]

        if captured_interrupt is not None:
            approval_request = _format_interrupt(runtime, captured_interrupt)
            snapshot = await graph.aget_state(config)
            state_values = dict(getattr(snapshot, "values", {}) or {})
            pending_text = str(state_values.get("pending_answer_text") or "").strip()
            if pending_text:
                await shared._persist_task_primary_message(
                    runtime,
                    conversation_id=shell["conversation_id"],
                    task_id=shell["task_id"],
                    message_id=shell["assistant_message_id"],
                    content=pending_text,
                    merge_with_existing=True,
                )
            approval = await mark_task_requires_action(
                runtime,
                conversation_id=shell["conversation_id"],
                task_id=shell["task_id"],
                tool_use_id=str(approval_request.get("interrupt_id") or ""),
                approval_request=approval_request,
                session_id=shell["session_id"],
                workspace_id=shell["workspace_id"],
            )
            await set_pending_approval_state(
                runtime,
                exists=True,
                conversation_id=int(shell["conversation_id"]),
                workspace_id=str(shell["workspace_id"] or "default"),
                action_name=str((approval_request.get("action_requests") or [{}])[0].get("name") or "").strip() or None,
            )
            yield make_sse_event(
                "approval",
                {
                    "session_id": shell["session_id"],
                    "workspace_id": shell["workspace_id"],
                    "task_id": shell["task_id"],
                    "tool_use_id": str(approval_request.get("interrupt_id") or ""),
                    "approval_id": approval.get("approval_id"),
                    "assistant_message_id": shell["assistant_message_id"],
                    "approval_request": approval_request,
                },
            )
            yield make_sse_event(
                "task_status",
                {
                    "task_id": shell["task_id"],
                    "assistant_message_id": shell["assistant_message_id"],
                    "status": "requires_action",
                    "phase": "waiting_approval",
                },
            )
            yield make_sse_event("skills", shared._build_skills_state(runtime, shell["session_id"]))
            yield make_sse_event("done", {})
            return

        await clear_pending_approval_state(
            runtime,
            conversation_id=shell["conversation_id"],
            workspace_id=shell["workspace_id"],
        )
        yield make_sse_event("done", {})
    finally:
        await shared._flush_persisted_event_tasks(persisted_event_tasks)


async def graph_resume_unified_agent(
    runtime: Runtime,
    *,
    session_id: str,
    decision: dict[str, Any],
    conversation_id: int | None,
    task_id: str | None,
    actor: str,
) -> dict[str, Any]:
    graph = getattr(runtime, "unified_agent_graph", None)
    if graph is None:
        raise RuntimeError("Unified agent graph is not initialized.")

    resolved_conversation_id = shared._resolve_conversation_id(session_id, conversation_id)
    resolved_task_id = str(task_id or "").strip()
    pending = await project_graph_pending_approval(
        runtime,
        conversation_id=resolved_conversation_id,
        task_id=resolved_task_id or None,
    )
    if not pending and not resolved_task_id:
        raise RuntimeError("当前没有待审批的操作。")
    pending_payload = dict(pending or {})
    resolved_task_id = resolved_task_id or str(pending_payload.get("task_id") or "").strip()
    if not resolved_task_id:
        raise RuntimeError("当前待审批记录缺少 task_id。")
    workspace_id = str(pending_payload.get("workspace_id") or "default").strip() or "default"
    persisted_event_tasks: list[asyncio.Task[None]] = []
    config = {"configurable": {"thread_id": f"task-{resolved_task_id}"}}
    context = {
        "runtime": runtime,
        "actor": actor,
        "approval_mode": None,
        "stream": False,
        "persisted_event_tasks": persisted_event_tasks,
    }

    try:
        result = await graph.ainvoke(Command(resume=decision), config, context=context)
        if isinstance(result, dict) and result.get("__interrupt__"):
            interrupt = result["__interrupt__"][0]
            approval_request = _format_interrupt(runtime, interrupt)
            snapshot = await graph.aget_state(config)
            state_values = dict(getattr(snapshot, "values", {}) or {})
            assistant_message_id = int(state_values.get("assistant_message_id") or pending_payload.get("assistant_message_id") or 0) or None
            approval = await mark_task_requires_action(
                runtime,
                conversation_id=resolved_conversation_id,
                task_id=resolved_task_id,
                tool_use_id=str(approval_request.get("interrupt_id") or ""),
                approval_request=approval_request,
                session_id=session_id,
                workspace_id=workspace_id,
            )
            await set_pending_approval_state(
                runtime,
                exists=True,
                conversation_id=int(resolved_conversation_id),
                workspace_id=str(workspace_id or "default"),
                action_name=str((approval_request.get("action_requests") or [{}])[0].get("name") or "").strip() or None,
            )
            return {
                "status": "pending_approval",
                "conversation_id": resolved_conversation_id,
                "session_id": session_id,
                "workspace_id": workspace_id,
                "task_id": resolved_task_id,
                "tool_use_id": str(approval_request.get("interrupt_id") or ""),
                "approval_id": approval.get("approval_id"),
                "assistant_message_id": assistant_message_id,
                "approval_request": approval_request,
                **shared._build_skills_state(runtime, session_id),
            }

        result = dict(result or {})
        if result.get("status") == "failed":
            raise RuntimeError(str(result.get("error") or "Unified agent graph 恢复执行失败"))
        await clear_pending_approval_state(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=workspace_id,
        )
        snapshot = await graph.aget_state(config)
        state_values = dict(getattr(snapshot, "values", {}) or {})
        return {
            "status": "completed",
            "conversation_id": resolved_conversation_id,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "task_id": resolved_task_id,
            "answer": str(result.get("answer_text") or ""),
            "assistant_message_id": int(state_values.get("assistant_message_id") or pending_payload.get("assistant_message_id") or 0) or None,
            **shared._build_skills_state(runtime, session_id),
        }
    finally:
        await shared._flush_persisted_event_tasks(persisted_event_tasks)


async def graph_stream_resume_unified_agent_events(
    runtime: Runtime,
    *,
    session_id: str,
    decision: dict[str, Any],
    conversation_id: int | None,
    task_id: str | None,
    actor: str,
) -> AsyncIterator[str]:
    graph = getattr(runtime, "unified_agent_graph", None)
    if graph is None:
        raise RuntimeError("Unified agent graph is not initialized.")

    resolved_conversation_id = shared._resolve_conversation_id(session_id, conversation_id)
    resolved_task_id = str(task_id or "").strip()
    pending = await project_graph_pending_approval(
        runtime,
        conversation_id=resolved_conversation_id,
        task_id=resolved_task_id or None,
    )
    if not pending and not resolved_task_id:
        raise RuntimeError("当前没有待审批的操作。")
    pending_payload = dict(pending or {})
    resolved_task_id = resolved_task_id or str(pending_payload.get("task_id") or "").strip()
    if not resolved_task_id:
        raise RuntimeError("当前待审批记录缺少 task_id。")
    workspace_id = str(pending_payload.get("workspace_id") or "default").strip() or "default"
    assistant_message_id = int(pending_payload.get("assistant_message_id") or 0) or None
    persisted_event_tasks: list[asyncio.Task[None]] = []
    config = {"configurable": {"thread_id": f"task-{resolved_task_id}"}}
    context = {
        "runtime": runtime,
        "actor": actor,
        "approval_mode": None,
        "stream": True,
        "persisted_event_tasks": persisted_event_tasks,
    }

    yield make_sse_event("conversation", {"conversation_id": resolved_conversation_id})
    yield make_sse_event("status", {"delta": "Agent 正在恢复执行..."})

    captured_interrupt = None
    try:
        async for chunk in graph.astream(
            Command(resume=decision),
            config,
            context=context,
            stream_mode=["custom", "updates"],
            version="v2",
        ):
            chunk_type = chunk.get("type")
            if chunk_type == "custom":
                payload = dict(chunk.get("data") or {})
                projected = _project_custom_stream_event(payload)
                if projected is not None:
                    yield projected
            elif chunk_type == "updates":
                data = dict(chunk.get("data") or {})
                interrupts = data.get("__interrupt__")
                if interrupts:
                    captured_interrupt = interrupts[0]

        if captured_interrupt is not None:
            approval_request = _format_interrupt(runtime, captured_interrupt)
            snapshot = await graph.aget_state(config)
            state_values = dict(getattr(snapshot, "values", {}) or {})
            assistant_message_id = int(state_values.get("assistant_message_id") or assistant_message_id or 0) or None
            approval = await mark_task_requires_action(
                runtime,
                conversation_id=resolved_conversation_id,
                task_id=resolved_task_id,
                tool_use_id=str(approval_request.get("interrupt_id") or ""),
                approval_request=approval_request,
                session_id=session_id,
                workspace_id=workspace_id,
            )
            await set_pending_approval_state(
                runtime,
                exists=True,
                conversation_id=int(resolved_conversation_id),
                workspace_id=str(workspace_id or "default"),
                action_name=str((approval_request.get("action_requests") or [{}])[0].get("name") or "").strip() or None,
            )
            yield make_sse_event(
                "approval",
                {
                    "session_id": session_id,
                    "workspace_id": workspace_id,
                    "task_id": resolved_task_id,
                    "tool_use_id": str(approval_request.get("interrupt_id") or ""),
                    "approval_id": approval.get("approval_id"),
                    "assistant_message_id": assistant_message_id,
                    "approval_request": approval_request,
                },
            )
            yield make_sse_event(
                "task_status",
                {
                    "task_id": task_id,
                    "assistant_message_id": assistant_message_id,
                    "status": "requires_action",
                    "phase": "waiting_approval",
                },
            )
            yield make_sse_event("skills", shared._build_skills_state(runtime, session_id))
            yield make_sse_event("done", {})
            return

        await clear_pending_approval_state(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=workspace_id,
        )
        yield make_sse_event("done", {})
    finally:
        await shared._flush_persisted_event_tasks(persisted_event_tasks)
