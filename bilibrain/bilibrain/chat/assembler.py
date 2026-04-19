from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from bilibrain.chat.paths import get_context_layers_path
from bilibrain.services.chat_memory import build_conversation_context, read_memory_sections
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
    selected_memory_section_ids: list[str]
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


def _query_terms(query: str) -> set[str]:
    normalized = str(query or "").lower()
    terms: set[str] = set()
    for raw in normalized.replace("，", " ").replace("。", " ").split():
        token = raw.strip(" -:：,.;；、()[]{}<>\"'`")
        if len(token) >= 2:
            terms.add(token)
    return terms


def _score_memory_section(section: dict[str, Any], query_terms: set[str]) -> int:
    score = 0
    section_type = str(section.get("type") or "").strip().lower()
    if section_type in {"active_goal", "active_scope"}:
        score += 2
    elif section_type == "recent_progress":
        score += 2
    elif section_type == "confirmed_fact":
        score += 1

    content = str(section.get("content") or "").lower()
    keywords = [str(item or "").lower() for item in list(section.get("keywords") or [])]
    for term in query_terms:
        if term in content:
            score += 3
        elif any(term in keyword or keyword in term for keyword in keywords if keyword):
            score += 3
    return score


def _select_memory_sections(
    sections: list[dict[str, Any]],
    *,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    query_terms = _query_terms(query)
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, section in enumerate(sections):
        score = _score_memory_section(section, query_terms)
        if score <= 0:
            continue
        scored.append((score, -index, section))
    scored.sort(reverse=True)
    return [item[2] for item in scored[: max(int(limit), 1)]]


def _format_memory_sections_for_prompt(sections: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for section in sections:
        section_type = str(section.get("type") or "").strip()
        content = str(section.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"[{section_type}] {content}")
    return "\n".join(lines).strip()


async def assemble_unified_agent_context(
    runtime: Runtime,
    *,
    conversation_id: int,
    query: str,
    system_prompt_builder: Callable[[str], str],
) -> AssembledContext:
    context = await build_conversation_context(
        runtime,
        conversation_id=conversation_id,
    )
    memory_sections = await read_memory_sections(
        runtime,
        conversation_id=conversation_id,
    )
    selected_memory_sections = _select_memory_sections(
        memory_sections,
        query=query,
    )
    memory_text = _format_memory_sections_for_prompt(selected_memory_sections)
    system_prompt = system_prompt_builder(memory_text)
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
    memory_token_estimate = estimate_text_tokens(memory_text)
    token_estimates = {
        "system": system_token_estimate,
        "live_prefix": live_prefix_token_estimate,
        "recent_history": recent_token_estimate,
        "memory_sections": memory_token_estimate,
        "workspace_state": workspace_context.token_estimate,
        "total": system_token_estimate
        + live_prefix_token_estimate
        + recent_token_estimate
        + memory_token_estimate
        + workspace_context.token_estimate,
    }
    selected_memory_section_ids = [
        str(item.get("section_id") or "").strip()
        for item in selected_memory_sections
        if str(item.get("section_id") or "").strip()
    ]

    snapshot = {
        "conversation_id": int(conversation_id),
        "query": str(query or ""),
        "assembled_at": _now_text(),
        "selected_live_prefix_message_ids": selected_live_prefix_ids,
        "selected_recent_message_ids": selected_recent_ids,
        "selected_memory_section_ids": selected_memory_section_ids,
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
        selected_memory_section_ids=selected_memory_section_ids,
        selected_workspace_state_keys=workspace_context.selected_keys,
        token_estimates=token_estimates,
        final_message_count=len(messages),
    )
