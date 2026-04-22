from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from bilibrain.services.chat_storage import (
    list_chat_session_messages,
    list_recent_chat_session_messages,
    read_chat_session_context_stats,
    read_chat_session_memory,
    write_chat_memory,
    write_context_stats,
)
from bilibrain.services.common import estimate_text_tokens

if TYPE_CHECKING:
    from bilibrain.core.runtime import Runtime


DEFAULT_RECENT_TURNS = 5


@dataclass
class ConversationContext:
    live_prefix_history: list[dict[str, Any]]
    recent_history: list[dict[str, Any]]
    memory_text: str
    compacted_until_message_id: int | None
    recent_start_message_id: int | None
    estimated_tokens: int
    memory_token_estimate: int
    live_prefix_token_estimate: int
    recent_token_estimate: int
    last_message_id: int | None

    @property
    def uncompacted_token_estimate(self) -> int:
        return self.live_prefix_token_estimate


def estimate_history_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for item in messages:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if not role or not content:
            continue
        total += estimate_text_tokens(f"{role}: {content}")
    return total


def split_recent_history(
    history: list[dict[str, Any]],
    *,
    keep_turns: int = DEFAULT_RECENT_TURNS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not history:
        return [], []

    safe_turns = max(int(keep_turns), 1)
    recent_reversed: list[dict[str, Any]] = []
    user_turns = 0

    for item in reversed(history):
        recent_reversed.append(item)
        if str(item.get("role") or "").strip().lower() == "user":
            user_turns += 1
            if user_turns >= safe_turns:
                break

    recent_history = list(reversed(recent_reversed))
    split_index = max(len(history) - len(recent_history), 0)
    return history[:split_index], recent_history


def format_history_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, item in enumerate(messages, start=1):
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        speaker = "用户" if role == "user" else "助手"
        lines.append(f"[{index}] {speaker}: {content}")
    return "\n".join(lines)


def _message_id(item: dict[str, Any]) -> int:
    return int(item.get("message_id") or 0)


def _group_history_by_user_turn(
    history: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    for item in history:
        role = str(item.get("role") or "").strip().lower()
        if role == "user" and current:
            groups.append(current)
            current = [item]
            continue
        current.append(item)

    if current:
        groups.append(current)
    return groups


def _select_compactable_history(
    history: list[dict[str, Any]],
    *,
    compacted_until_message_id: int | None,
    recent_start_message_id: int | None,
) -> list[dict[str, Any]]:
    if recent_start_message_id is None:
        return []
    result: list[dict[str, Any]] = []
    for group in _group_history_by_user_turn(history):
        if not group:
            continue
        first_message_id = _message_id(group[0])
        last_message_id = _message_id(group[-1])
        if (
            compacted_until_message_id is not None
            and last_message_id <= int(compacted_until_message_id)
        ):
            continue
        if first_message_id >= int(recent_start_message_id):
            continue
        if last_message_id >= int(recent_start_message_id):
            continue
        result.extend(group)
    return result


def _build_context_from_stats(
    live_prefix_history: list[dict[str, Any]],
    recent_history: list[dict[str, Any]],
    memory_row: dict[str, Any] | None,
    stats_row: dict[str, Any],
) -> ConversationContext:
    memory_text = str(memory_row.get("memory_text") or "").strip() if memory_row else ""
    memory_token_estimate = int(
        stats_row.get("memory_token_estimate") or estimate_text_tokens(memory_text)
    )
    live_prefix_token_estimate = int(stats_row.get("uncompacted_token_estimate") or 0)
    recent_token_estimate = int(
        stats_row.get("recent_token_estimate")
        or estimate_history_tokens(recent_history)
    )
    return ConversationContext(
        live_prefix_history=live_prefix_history,
        recent_history=recent_history,
        memory_text=memory_text,
        compacted_until_message_id=int(stats_row["compacted_until_message_id"])
        if stats_row.get("compacted_until_message_id")
        else None,
        recent_start_message_id=int(stats_row["recent_start_message_id"])
        if stats_row.get("recent_start_message_id")
        else (_message_id(recent_history[0]) if recent_history else None),
        estimated_tokens=memory_token_estimate
        + live_prefix_token_estimate
        + recent_token_estimate,
        memory_token_estimate=memory_token_estimate,
        live_prefix_token_estimate=live_prefix_token_estimate,
        recent_token_estimate=recent_token_estimate,
        last_message_id=int(stats_row["last_message_id"])
        if stats_row.get("last_message_id")
        else (_message_id(recent_history[-1]) if recent_history else None),
    )


def _derive_context_stats_payload(
    full_history: list[dict[str, Any]],
    *,
    memory_text: str,
    compacted_until_message_id: int | None,
    keep_turns: int,
) -> dict[str, Any]:
    _, recent_history = split_recent_history(
        full_history,
        keep_turns=keep_turns,
    )
    recent_start_message_id = (
        _message_id(recent_history[0]) if recent_history else None
    )
    compactable_history = _select_compactable_history(
        full_history,
        compacted_until_message_id=int(compacted_until_message_id)
        if compacted_until_message_id is not None
        else None,
        recent_start_message_id=recent_start_message_id,
    )
    return {
        "last_message_id": _message_id(full_history[-1]) if full_history else None,
        "compacted_until_message_id": int(compacted_until_message_id)
        if compacted_until_message_id is not None
        else None,
        "recent_start_message_id": recent_start_message_id,
        "memory_token_estimate": estimate_text_tokens(memory_text),
        "uncompacted_token_estimate": estimate_history_tokens(compactable_history),
        "recent_token_estimate": estimate_history_tokens(recent_history),
    }


async def _recompute_context_stats(
    runtime: Runtime,
    conversation_id: int,
    *,
    memory_text_override: str | None = None,
    compacted_until_message_id_override: int | None = None,
) -> dict[str, Any]:
    full_history = await list_chat_session_messages(runtime, conversation_id)
    memory_row = await read_chat_session_memory(runtime, conversation_id)
    memory_text = (
        str(memory_text_override).strip()
        if memory_text_override is not None
        else str(memory_row.get("memory_text") or "").strip()
        if memory_row
        else ""
    )
    compacted_until_message_id = (
        int(compacted_until_message_id_override)
        if compacted_until_message_id_override is not None
        else (
        int(memory_row["compacted_until_message_id"])
        if memory_row and memory_row.get("compacted_until_message_id") is not None
        else None
        )
    )
    payload = _derive_context_stats_payload(
        full_history,
        memory_text=memory_text,
        compacted_until_message_id=compacted_until_message_id,
        keep_turns=runtime.settings.chat_recent_turns_to_keep,
    )
    return await write_context_stats(
        runtime,
        conversation_id,
        **payload,
    )


async def _bootstrap_context_stats(
    runtime: Runtime, conversation_id: int
) -> dict[str, Any]:
    return await _recompute_context_stats(runtime, conversation_id)


async def build_conversation_context(
    runtime: Runtime,
    *,
    conversation_id: int,
) -> ConversationContext:
    stats_row = await read_chat_session_context_stats(runtime, conversation_id)
    memory_row = await read_chat_session_memory(runtime, conversation_id)
    recent_history = await list_recent_chat_session_messages(
        runtime,
        conversation_id,
        keep_turns=runtime.settings.chat_recent_turns_to_keep,
    )
    full_history = await list_chat_session_messages(runtime, conversation_id)
    expected_recent_start_message_id = (
        _message_id(recent_history[0]) if recent_history else None
    )
    expected_last_message_id = _message_id(recent_history[-1]) if recent_history else None
    expected_compacted_until_message_id = (
        int(memory_row["compacted_until_message_id"])
        if memory_row and memory_row.get("compacted_until_message_id") is not None
        else None
    )
    if (
        not stats_row
        or (
            int(stats_row["recent_start_message_id"])
            if stats_row.get("recent_start_message_id") is not None
            else None
        )
        != expected_recent_start_message_id
        or (
            int(stats_row["last_message_id"])
            if stats_row.get("last_message_id") is not None
            else None
        )
        != expected_last_message_id
        or (
            int(stats_row["compacted_until_message_id"])
            if stats_row.get("compacted_until_message_id") is not None
            else None
        )
        != expected_compacted_until_message_id
    ):
        stats_row = await _recompute_context_stats(runtime, conversation_id)
    live_prefix_history = _select_compactable_history(
        full_history,
        compacted_until_message_id=(
            int(stats_row["compacted_until_message_id"])
            if stats_row.get("compacted_until_message_id") is not None
            else None
        ),
        recent_start_message_id=(
            int(stats_row["recent_start_message_id"])
            if stats_row.get("recent_start_message_id") is not None
            else None
        ),
    )
    return _build_context_from_stats(
        live_prefix_history,
        recent_history,
        memory_row,
        stats_row,
    )


def should_compact_context(
    runtime: Runtime,
    context: ConversationContext,
    *,
    extra_token_budget: int = 0,
) -> bool:
    if context.recent_start_message_id is None:
        return False
    if context.last_message_id is None:
        return False
    if context.live_prefix_token_estimate <= 0:
        return False
    return (context.estimated_tokens + max(int(extra_token_budget), 0)) >= int(
        runtime.settings.chat_compaction_trigger_tokens
    )


async def compact_conversation_context(
    runtime: Runtime,
    *,
    conversation_id: int,
    context: ConversationContext,
) -> ConversationContext:
    if context.recent_start_message_id is None:
        return context

    full_history = await list_chat_session_messages(runtime, conversation_id)
    compactable_history = _select_compactable_history(
        full_history,
        compacted_until_message_id=context.compacted_until_message_id,
        recent_start_message_id=context.recent_start_message_id,
    )
    if not compactable_history:
        await _recompute_context_stats(runtime, conversation_id)
        return await build_conversation_context(
            runtime, conversation_id=conversation_id
        )

    transcript = format_history_transcript(compactable_history)
    if not transcript:
        return context

    memory_text = await runtime.qwen.compact_conversation_memory(
        existing_memory_text=context.memory_text,
        history_transcript=transcript,
    )
    latest_message_id = max(_message_id(item) for item in compactable_history)
    await write_chat_memory(
        runtime,
        conversation_id,
        memory_text=memory_text,
        compacted_until_message_id=latest_message_id,
    )
    await _recompute_context_stats(
        runtime,
        conversation_id,
        memory_text_override=memory_text,
        compacted_until_message_id_override=latest_message_id,
    )
    return await build_conversation_context(runtime, conversation_id=conversation_id)


async def refresh_context_stats_after_message(
    runtime: Runtime,
    *,
    conversation_id: int,
    message: dict[str, Any],
) -> dict[str, Any]:
    _ = message
    return await _recompute_context_stats(runtime, conversation_id)
