from __future__ import annotations

import asyncio
from uuid import uuid4
from typing import Any, Callable

from bilibrain.services.chat_storage import (
    append_chat_tool_event,
    append_chat_task_event,
)
from bilibrain.services.runtime_state import (
    set_pending_approval_state,
    write_runtime_state,
    read_runtime_state,
)


async def clear_pending_approval_state(
    runtime,
    *,
    conversation_id: int,
    workspace_id: str,
) -> None:
    await set_pending_approval_state(
        runtime,
        exists=False,
        conversation_id=int(conversation_id),
        workspace_id=str(workspace_id or "default"),
    )


async def _sync_runtime_state_from_tool_event(
    runtime,
    *,
    conversation_id: int,
    workspace_id: str,
    payload: dict[str, Any],
) -> None:
    phase = str(payload.get("phase") or "").strip().lower()
    tool_name = str(payload.get("name") or "").strip()
    if phase != "finish" or not tool_name:
        return

    summary = dict(payload.get("summary") or {})
    state = await read_runtime_state(runtime)
    state["workspace_id"] = str(workspace_id or "default")
    if tool_name in {"write_file", "append_file", "make_dir", "obsidian_write_note"}:
        path = str(summary.get("path") or "").strip()
        state["last_write_file"] = {
            "path": path or None,
            "summary": f"最近一次 {tool_name} 操作作用于 {path}" if path else f"最近一次执行了 {tool_name}",
            "conversation_id": int(conversation_id),
            "timestamp": payload.get("timestamp"),
        }
    elif tool_name == "run_command":
        command = str(summary.get("command") or "").strip()
        state["last_run_command"] = {
            "command": command or None,
            "summary": f"最近一次执行命令：{command}" if command else "最近一次执行了命令",
            "ok": bool(payload.get("ok")),
            "conversation_id": int(conversation_id),
            "timestamp": payload.get("timestamp"),
        }
    elif tool_name == "read_file":
        path = str(summary.get("path") or "").strip()
        if path:
            reads = list(state.get("recent_file_reads") or [])
            reads.insert(
                0,
                {
                    "path": path,
                    "conversation_id": int(conversation_id),
                    "timestamp": payload.get("timestamp"),
                },
            )
            state["recent_file_reads"] = reads[:5]
    await write_runtime_state(runtime, state)


async def persist_runtime_event(
    runtime,
    *,
    conversation_id: int,
    workspace_id: str,
    event_type: str,
    payload: dict[str, Any],
    task_id: str | None = None,
) -> None:
    normalized_type = str(event_type or "").strip().lower()
    event_payload = dict(payload or {})
    if normalized_type not in {"tool", "skill", "approval"}:
        return
    await append_chat_tool_event(
        runtime,
        conversation_id,
        event_type=normalized_type,
        payload=event_payload,
    )
    normalized_task_id = str(task_id or "").strip()
    if normalized_task_id:
        await append_chat_task_event(
            runtime,
            int(conversation_id),
            event_id=f"{normalized_task_id}:{normalized_type}:{uuid4().hex[:8]}",
            task_id=normalized_task_id,
            tool_use_id=str(event_payload.get("id") or event_payload.get("tool_use_id") or "").strip() or None,
            event_type=normalized_type,
            payload=event_payload,
        )
    if normalized_type == "tool":
        await _sync_runtime_state_from_tool_event(
            runtime,
            conversation_id=int(conversation_id),
            workspace_id=str(workspace_id or "default"),
            payload=event_payload,
        )


def build_persisting_runtime_event_callback(
    runtime,
    *,
    conversation_id: int,
    workspace_id: str,
    downstream: Callable[[str, dict[str, Any]], None] | None,
    tasks: list[asyncio.Task[None]],
    task_id: str | None = None,
) -> Callable[[str, dict[str, Any]], None]:
    def emit(event_type: str, data: dict[str, Any] | None = None) -> None:
        payload = dict(data or {})
        normalized_type = str(event_type or "").strip().lower()
        if normalized_type in {"tool", "skill", "approval"}:
            tasks.append(
                asyncio.create_task(
                    persist_runtime_event(
                        runtime,
                        conversation_id=int(conversation_id),
                        workspace_id=str(workspace_id or "default"),
                        event_type=normalized_type,
                        payload=payload,
                        task_id=task_id,
                    )
                )
            )
        if downstream is not None:
            downstream(event_type, payload)

    return emit
