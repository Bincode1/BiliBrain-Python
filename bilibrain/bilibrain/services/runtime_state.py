from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from bilibrain.chat.paths import get_runtime_state_path


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _default_state() -> dict[str, Any]:
    return {
        "workspace_id": "default",
        "updated_at": None,
        "last_write_file": None,
        "last_run_command": None,
        "pending_approval": {"exists": False},
        "recent_file_reads": [],
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


async def read_runtime_state(runtime) -> dict[str, Any]:
    path = get_runtime_state_path(runtime.settings)
    if not path.exists():
        return _default_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _default_state()
    if not isinstance(payload, dict):
        return _default_state()
    state = _default_state()
    state.update(payload)
    return state


async def write_runtime_state(runtime, state: dict[str, Any]) -> dict[str, Any]:
    payload = _default_state()
    payload.update(dict(state or {}))
    payload["updated_at"] = _now_text()
    _write_json_atomic(get_runtime_state_path(runtime.settings), payload)
    return payload


async def set_pending_approval_state(
    runtime,
    *,
    exists: bool,
    conversation_id: int | None = None,
    workspace_id: str = "default",
    action_name: str | None = None,
) -> dict[str, Any]:
    state = await read_runtime_state(runtime)
    state["workspace_id"] = str(workspace_id or "default")
    if exists:
        state["pending_approval"] = {
            "exists": True,
            "conversation_id": int(conversation_id) if conversation_id is not None else None,
            "workspace_id": str(workspace_id or "default"),
            "action_name": str(action_name or "").strip() or None,
            "updated_at": _now_text(),
        }
    else:
        state["pending_approval"] = {"exists": False}
    return await write_runtime_state(runtime, state)


def _extract_tool_result_payload(result_str: str) -> dict[str, Any]:
    try:
        payload = json.loads(result_str)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    result_payload = payload.get("payload")
    return result_payload if isinstance(result_payload, dict) else {}


async def update_runtime_state_from_tool_execution(
    runtime,
    *,
    conversation_id: int,
    workspace_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
    result_str: str,
) -> dict[str, Any]:
    state = await read_runtime_state(runtime)
    state["workspace_id"] = str(workspace_id or "default")
    payload = _extract_tool_result_payload(result_str)
    timestamp = _now_text()

    if tool_name in {"write_file", "append_file", "make_dir"}:
        path = str(payload.get("path") or tool_args.get("path") or "").strip()
        state["last_write_file"] = {
            "path": path or None,
            "summary": f"最近一次 {tool_name} 操作作用于 {path}" if path else f"最近一次执行了 {tool_name}",
            "conversation_id": int(conversation_id),
            "timestamp": timestamp,
        }
    elif tool_name == "run_command":
        command = str(tool_args.get("command") or "").strip()
        state["last_run_command"] = {
            "command": command or None,
            "summary": f"最近一次执行命令：{command}" if command else "最近一次执行了命令",
            "ok": "error" not in str(result_str or "").lower(),
            "conversation_id": int(conversation_id),
            "timestamp": timestamp,
        }
    elif tool_name == "read_file":
        path = str(payload.get("path") or tool_args.get("path") or "").strip()
        if path:
            reads = list(state.get("recent_file_reads") or [])
            reads.insert(
                0,
                {
                    "path": path,
                    "conversation_id": int(conversation_id),
                    "timestamp": timestamp,
                },
            )
            state["recent_file_reads"] = reads[:5]

    return await write_runtime_state(runtime, state)
