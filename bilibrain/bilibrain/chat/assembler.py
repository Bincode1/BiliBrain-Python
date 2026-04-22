from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from bilibrain.chat.paths import get_context_layers_path
from bilibrain.services.chat_memory import build_conversation_context
from bilibrain.services.common import estimate_text_tokens
from bilibrain.services.workspace_context import select_workspace_context

if TYPE_CHECKING:
    from bilibrain.core.runtime import Runtime


@dataclass
class AssembledContext:
    system_prompt: str
    messages: list[Any]
    selected_live_prefix_message_ids: list[int]
    selected_recent_message_ids: list[int]
    selected_workspace_state_keys: list[str]
    token_estimates: dict[str, int]
    final_message_count: int


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _history_to_messages(
    history: list[dict[str, Any]],
) -> tuple[list[Any], list[int], int]:
    messages: list[Any] = []
    selected_ids: list[int] = []
    history_token_estimate = 0

    for item in history:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        message_id = int(item.get("message_id") or 0)
        if role not in {"user", "assistant"} or not content:
            continue
        selected_ids.append(message_id)
        history_token_estimate += estimate_text_tokens(
            f"{'human' if role == 'user' else 'ai'}: {content}"
        )
        if role == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))

    return messages, selected_ids, history_token_estimate


async def assemble_unified_agent_context(
    runtime: Runtime,
    *,
    conversation_id: int,
    query: str,
    system_prompt_builder: Callable[[str], str],
    system_context_builder: Callable[[str], str | None] | None = None,
) -> AssembledContext:
    context = await build_conversation_context(
        runtime,
        conversation_id=conversation_id,
    )
    memory_text = str(context.memory_text or "").strip()
    system_prompt = system_prompt_builder(memory_text)
    system_context_prompt = (
        str(system_context_builder(memory_text) or "").strip()
        if system_context_builder is not None
        else ""
    )
    workspace_context = await select_workspace_context(
        runtime,
        query=query,
    )
    live_prefix_messages, selected_live_prefix_ids, live_prefix_token_estimate = _history_to_messages(
        context.live_prefix_history,
    )
    recent_messages, selected_recent_ids, recent_token_estimate = _history_to_messages(
        context.recent_history,
    )
    messages: list[Any] = [SystemMessage(content=system_prompt)]
    if system_context_prompt:
        messages.append(SystemMessage(content=system_context_prompt))
    if workspace_context.prompt_text:
        messages.append(
            SystemMessage(
                content="\n".join(
                    [
                        "以下是当前共享 workspace 的运行态摘要，仅在与当前问题直接相关时使用：",
                        workspace_context.prompt_text,
                    ]
                )
            )
        )
    messages.extend(live_prefix_messages)
    messages.extend(recent_messages)
    normalized_query = str(query or "").strip()
    if normalized_query:
        last_message = messages[-1] if messages else None
        last_content = str(getattr(last_message, "content", "") or "").strip()
        if not isinstance(last_message, HumanMessage) or last_content != normalized_query:
            messages.append(HumanMessage(content=normalized_query))
    system_token_estimate = estimate_text_tokens(system_prompt)
    system_context_token_estimate = estimate_text_tokens(system_context_prompt)
    memory_token_estimate = estimate_text_tokens(memory_text)
    token_estimates = {
        "system": system_token_estimate,
        "system_context": system_context_token_estimate,
        "live_prefix": live_prefix_token_estimate,
        "recent_history": recent_token_estimate,
        "memory_text": memory_token_estimate,
        "workspace_state": workspace_context.token_estimate,
        "total": system_token_estimate
        + system_context_token_estimate
        + live_prefix_token_estimate
        + recent_token_estimate
        + memory_token_estimate
        + workspace_context.token_estimate,
    }
    snapshot = {
        "conversation_id": int(conversation_id),
        "query": str(query or ""),
        "assembled_at": _now_text(),
        "selected_live_prefix_message_ids": selected_live_prefix_ids,
        "selected_recent_message_ids": selected_recent_ids,
        "selected_workspace_state_keys": workspace_context.selected_keys,
        "token_estimates": token_estimates,
        "final_message_count": len(messages),
    }
    _write_json_atomic(
        get_context_layers_path(runtime.settings, int(conversation_id)),
        snapshot,
    )

    return AssembledContext(
        system_prompt=system_prompt,
        messages=messages,
        selected_live_prefix_message_ids=selected_live_prefix_ids,
        selected_recent_message_ids=selected_recent_ids,
        selected_workspace_state_keys=workspace_context.selected_keys,
        token_estimates=token_estimates,
        final_message_count=len(messages),
    )
