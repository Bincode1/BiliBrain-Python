from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from bilibrain.services.chat_storage import (
    append_chat_approval,
    append_chat_message,
    append_chat_task,
    append_chat_task_event,
    get_chat_session_task,
    list_chat_session_approvals,
    replace_chat_approval,
    replace_chat_task,
)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_task_id() -> str:
    return f"task-{uuid4().hex}"


async def _resolve_latest_approval_id(
    runtime,
    *,
    conversation_id: int,
    task_id: str,
    tool_use_id: str | None = None,
) -> str | None:
    approvals = await list_chat_session_approvals(
        runtime,
        int(conversation_id),
        task_id=task_id,
    )
    normalized_tool_use_id = str(tool_use_id or "").strip()
    candidates = [
        item
        for item in approvals
        if str(item.get("status") or "").strip().lower() == "pending"
        and (
            not normalized_tool_use_id
            or str(item.get("tool_use_id") or "").strip() == normalized_tool_use_id
        )
    ]
    if not candidates and normalized_tool_use_id:
        candidates = [
            item
            for item in approvals
            if str(item.get("tool_use_id") or "").strip() == normalized_tool_use_id
        ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
    )
    return str(candidates[-1].get("approval_id") or "").strip() or None


async def create_task_shell(
    runtime,
    *,
    conversation_id: int,
    query: str,
) -> dict[str, Any]:
    task_id = build_task_id()
    user_message = await append_chat_message(
        runtime,
        conversation_id,
        "user",
        query,
        task_id=task_id,
        message_kind="user_prompt",
    )
    task = await append_chat_task(
        runtime,
        conversation_id,
        task_id=task_id,
        user_message_id=int(user_message["message_id"]),
        status="running",
        phase="preparing",
        metadata={"query": str(query or "").strip()},
    )
    await append_chat_task_event(
        runtime,
        conversation_id,
        event_id=f"{task_id}:created",
        task_id=task_id,
        event_type="task_created",
        payload={
            "task_id": task_id,
            "query": str(query or "").strip(),
            "user_message_id": int(user_message["message_id"]),
        },
    )
    return {
        "task_id": task_id,
        "user_message": user_message,
        "task": task,
    }


async def ensure_task_assistant_placeholder(
    runtime,
    *,
    conversation_id: int,
    task_id: str,
) -> dict[str, Any]:
    task = await get_chat_session_task(runtime, conversation_id, task_id)
    if task is None:
        raise RuntimeError(f"Task not found: {task_id}")
    assistant_message_id = task.get("assistant_message_id")
    if assistant_message_id:
        return task

    assistant_message = await append_chat_message(
        runtime,
        conversation_id,
        "assistant",
        "",
        task_id=task_id,
        message_kind="task_primary",
    )
    updated = await replace_chat_task(
        runtime,
        conversation_id,
        task_id=task_id,
        assistant_message_id=int(assistant_message["message_id"]),
        phase="running",
    )
    await append_chat_task_event(
        runtime,
        conversation_id,
        event_id=f"{task_id}:assistant_started:{assistant_message['message_id']}",
        task_id=task_id,
        event_type="assistant_started",
        payload={"assistant_message_id": int(assistant_message["message_id"])},
    )
    return updated or task


async def mark_task_phase(
    runtime,
    *,
    conversation_id: int,
    task_id: str,
    phase: str,
    status: str | None = None,
    pending_tool_use_id: str | None = None,
    failure_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    updated = await replace_chat_task(
        runtime,
        conversation_id,
        task_id=task_id,
        phase=phase,
        status=status,
        pending_tool_use_id=pending_tool_use_id,
        failure_reason=failure_reason,
        metadata=metadata,
    )
    await append_chat_task_event(
        runtime,
        conversation_id,
        event_id=f"{task_id}:phase:{uuid4().hex[:8]}",
        task_id=task_id,
        tool_use_id=pending_tool_use_id,
        event_type="phase_changed",
        payload={
            "phase": phase,
            "status": status,
            "pending_tool_use_id": pending_tool_use_id,
            "failure_reason": failure_reason,
        },
    )
    return updated


async def mark_task_requires_action(
    runtime,
    *,
    conversation_id: int,
    task_id: str,
    tool_use_id: str,
    approval_request: dict[str, Any],
    session_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    approval = await append_chat_approval(
        runtime,
        conversation_id,
        approval_id=f"approval-{uuid4().hex}",
        task_id=task_id,
        tool_use_id=tool_use_id,
        status="pending",
        request_payload={
            "session_id": session_id,
            "workspace_id": workspace_id,
            "approval_request": approval_request,
        },
    )
    await mark_task_phase(
        runtime,
        conversation_id=conversation_id,
        task_id=task_id,
        phase="waiting_approval",
        status="requires_action",
        pending_tool_use_id=tool_use_id,
    )
    await append_chat_task_event(
        runtime,
        conversation_id,
        event_id=f"{task_id}:approval_requested:{tool_use_id}",
        task_id=task_id,
        tool_use_id=tool_use_id,
        event_type="approval_requested",
        payload={
            "approval_id": approval["approval_id"],
            "session_id": session_id,
            "workspace_id": workspace_id,
        },
    )
    return approval


async def mark_task_running_after_approval(
    runtime,
    *,
    conversation_id: int,
    task_id: str,
    tool_use_id: str,
    decision: dict[str, Any],
) -> None:
    approval_id = str((decision or {}).get("approval_id") or "").strip()
    if not approval_id:
        approval_id = (
            await _resolve_latest_approval_id(
                runtime,
                conversation_id=conversation_id,
                task_id=task_id,
                tool_use_id=tool_use_id,
            )
            or ""
        )
    if approval_id:
        await replace_chat_approval(
            runtime,
            conversation_id,
            approval_id=approval_id,
            status="approved",
            decision_payload=decision,
            resolved_at=_now_text(),
        )
    await mark_task_phase(
        runtime,
        conversation_id=conversation_id,
        task_id=task_id,
        phase="running",
        status="running",
        pending_tool_use_id="",
    )
    await append_chat_task_event(
        runtime,
        conversation_id,
        event_id=f"{task_id}:approval_resolved:{tool_use_id}",
        task_id=task_id,
        tool_use_id=tool_use_id,
        event_type="approval_resolved",
        payload={"decision": dict(decision or {})},
    )


async def mark_task_rejected(
    runtime,
    *,
    conversation_id: int,
    task_id: str,
    tool_use_id: str,
    approval_id: str | None,
    decision: dict[str, Any],
    failure_reason: str,
) -> None:
    if approval_id:
        await replace_chat_approval(
            runtime,
            conversation_id,
            approval_id=approval_id,
            status="rejected",
            decision_payload=decision,
            resolved_at=_now_text(),
        )
    else:
        resolved_approval_id = await _resolve_latest_approval_id(
            runtime,
            conversation_id=conversation_id,
            task_id=task_id,
            tool_use_id=tool_use_id,
        )
        if resolved_approval_id:
            await replace_chat_approval(
                runtime,
                conversation_id,
                approval_id=resolved_approval_id,
                status="rejected",
                decision_payload=decision,
                resolved_at=_now_text(),
            )
    await mark_task_failed(
        runtime,
        conversation_id=conversation_id,
        task_id=task_id,
        failure_reason=failure_reason,
        phase="rejected",
    )
    await append_chat_task_event(
        runtime,
        conversation_id,
        event_id=f"{task_id}:approval_rejected:{tool_use_id}",
        task_id=task_id,
        tool_use_id=tool_use_id,
        event_type="approval_resolved",
        payload={"decision": dict(decision or {}), "status": "rejected"},
    )


async def mark_task_completed(
    runtime,
    *,
    conversation_id: int,
    task_id: str,
    route_mode: str | None = None,
    answer_mode: str | None = None,
) -> dict[str, Any] | None:
    completed_at = _now_text()
    updated = await replace_chat_task(
        runtime,
        conversation_id,
        task_id=task_id,
        status="completed",
        phase="completed",
        route_mode=route_mode,
        answer_mode=answer_mode,
        pending_tool_use_id="",
        completed_at=completed_at,
    )
    await append_chat_task_event(
        runtime,
        conversation_id,
        event_id=f"{task_id}:completed",
        task_id=task_id,
        event_type="task_completed",
        payload={"route_mode": route_mode, "answer_mode": answer_mode},
    )
    return updated


async def mark_command_failed(
    runtime,
    *,
    conversation_id: int,
    task_id: str,
    command: str,
    exit_code: int,
    stderr: str,
    retry_count: int,
) -> dict[str, Any] | None:
    failure_reason = f"Command failed with exit code {exit_code}: {command}"
    if stderr:
        failure_reason += f" | stderr: {stderr[:200]}"
    updated = await replace_chat_task(
        runtime,
        conversation_id,
        task_id=task_id,
        status="running",
        phase="command_failed",
        failure_reason=failure_reason,
        retry_count=retry_count,
        pending_tool_use_id="",
    )
    await append_chat_task_event(
        runtime,
        conversation_id,
        event_id=f"{task_id}:command_failed:{uuid4().hex[:8]}",
        task_id=task_id,
        event_type="command_failed",
        payload={
            "command": command,
            "exit_code": exit_code,
            "stderr": stderr[:500] if stderr else "",
            "retry_count": retry_count,
        },
    )
    return updated


async def mark_task_failed(
    runtime,
    *,
    conversation_id: int,
    task_id: str,
    failure_reason: str,
    phase: str = "failed",
) -> dict[str, Any] | None:
    updated = await replace_chat_task(
        runtime,
        conversation_id,
        task_id=task_id,
        status="failed",
        phase=phase,
        failure_reason=failure_reason,
        pending_tool_use_id="",
        completed_at=_now_text(),
    )
    await append_chat_task_event(
        runtime,
        conversation_id,
        event_id=f"{task_id}:failed:{uuid4().hex[:8]}",
        task_id=task_id,
        event_type="task_failed",
        payload={"failure_reason": failure_reason, "phase": phase},
    )
    return updated
