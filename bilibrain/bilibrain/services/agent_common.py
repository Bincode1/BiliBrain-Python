from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from bilibrain.services.chat_storage import (
    create_chat_session,
    get_chat_session,
)
from bilibrain.tools.policy import evaluate_command_request

if TYPE_CHECKING:
    from bilibrain.core.runtime import Runtime


def summarize_tool_result_answer(
    tool_name: str,
    effective_args: dict[str, Any],
    result_str: str,
    fallback: str,
) -> str:
    try:
        payload = json.loads(result_str)
    except json.JSONDecodeError:
        return fallback
    if not isinstance(payload, dict):
        return fallback

    if payload.get("error"):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail") or str(error)
        else:
            message = str(error)
        return message or fallback

    result_payload = payload.get("payload")
    if not isinstance(result_payload, dict):
        return fallback

    if tool_name == "write_file":
        path = str(result_payload.get("path") or effective_args.get("path") or "").strip()
        return f"文件 `{path}` 已成功创建。"
    if tool_name == "append_file":
        path = str(result_payload.get("path") or effective_args.get("path") or "").strip()
        return f"内容已成功追加到文件 `{path}`。"
    if tool_name == "make_dir":
        path = str(result_payload.get("path") or effective_args.get("path") or "").strip()
        return f"目录 `{path}` 已成功创建。"
    if tool_name == "obsidian_write_note":
        path = str(result_payload.get("path") or effective_args.get("path") or "").strip()
        return f"Obsidian 笔记 `{path}` 已成功写入并校验完成。"
    if tool_name == "run_command":
        if fallback and fallback not in ("", "当前没有生成有效回答。"):
            return fallback
        return "命令已执行完成。"
    return fallback


async def get_or_create_conversation(
    runtime: Runtime,
    conversation_id: int | None,
) -> dict[str, Any]:
    if conversation_id:
        conversation = await get_chat_session(runtime, int(conversation_id))
        if not conversation:
            raise RuntimeError("对话会话不存在，请刷新页面后重试。")
        return conversation
    return await create_chat_session(runtime, folder_id=None, title="")


async def get_default_workspace(
    runtime: Runtime,
    *,
    actor: str,
) -> dict[str, Any]:
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")
    return await runtime.tool_service.get_or_create_default_workspace(actor=actor)


def format_interrupt(runtime: Runtime, interrupt: Any) -> dict[str, Any]:
    value = interrupt.value if hasattr(interrupt, "value") else {}
    payload = value if isinstance(value, dict) else {}
    action_requests = []
    for item in list(payload.get("action_requests") or []):
        action = dict(item or {})
        tool_policy = (
            getattr(runtime.tool_service, "policy", None)
            if runtime.tool_service is not None
            else None
        )
        if action.get("name") == "run_command" and tool_policy is not None:
            decision = evaluate_command_request(
                tool_policy,
                str((action.get("args") or {}).get("command") or ""),
                script_body=str((action.get("args") or {}).get("script_body") or "") or None,
            )
            action["policy_allowed"] = bool(decision.allowed)
            action["policy_requires_approval"] = bool(decision.requires_approval)
            action["policy_reason"] = decision.reason
            action["policy_blocked"] = not bool(decision.allowed)
        else:
            action["policy_allowed"] = True
            action["policy_requires_approval"] = False
            action["policy_reason"] = ""
            action["policy_blocked"] = False
        action_requests.append(action)
    return {
        "interrupt_id": str(payload.get("interrupt_id") or getattr(interrupt, "id", "") or "").strip(),
        "action_requests": action_requests,
        "review_configs": list(payload.get("review_configs") or []),
    }
