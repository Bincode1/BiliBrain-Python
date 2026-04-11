from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from bilibrain.services.common import estimate_text_tokens

if TYPE_CHECKING:
    from bilibrain.core.runtime import Runtime


DEFAULT_RECENT_TURNS = 5


@dataclass
class ConversationContext:
    recent_history: list[dict[str, Any]]
    memory_text: str
    compacted_until_message_id: int | None
    recent_start_message_id: int | None
    estimated_tokens: int
    memory_token_estimate: int
    uncompacted_token_estimate: int
    recent_token_estimate: int
    last_message_id: int | None


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


def _build_context_from_stats(
    recent_history: list[dict[str, Any]],
    memory_row: dict[str, Any] | None,
    stats_row: dict[str, Any],
) -> ConversationContext:
    memory_text = str(memory_row.get("memory_text") or "").strip() if memory_row else ""
    memory_token_estimate = int(
        stats_row.get("memory_token_estimate") or estimate_text_tokens(memory_text)
    )
    uncompacted_token_estimate = int(stats_row.get("uncompacted_token_estimate") or 0)
    recent_token_estimate = int(
        stats_row.get("recent_token_estimate")
        or estimate_history_tokens(recent_history)
    )
    return ConversationContext(
        recent_history=recent_history,
        memory_text=memory_text,
        compacted_until_message_id=int(stats_row["compacted_until_message_id"])
        if stats_row.get("compacted_until_message_id")
        else None,
        recent_start_message_id=int(stats_row["recent_start_message_id"])
        if stats_row.get("recent_start_message_id")
        else (_message_id(recent_history[0]) if recent_history else None),
        estimated_tokens=memory_token_estimate
        + uncompacted_token_estimate
        + recent_token_estimate,
        memory_token_estimate=memory_token_estimate,
        uncompacted_token_estimate=uncompacted_token_estimate,
        recent_token_estimate=recent_token_estimate,
        last_message_id=int(stats_row["last_message_id"])
        if stats_row.get("last_message_id")
        else (_message_id(recent_history[-1]) if recent_history else None),
    )


async def _bootstrap_context_stats(
    runtime: Runtime, conversation_id: int
) -> dict[str, Any]:
    full_history = await runtime.db.list_chat_messages(conversation_id)
    memory_row = await runtime.db.get_chat_conversation_memory(conversation_id)
    memory_text = str(memory_row.get("memory_text") or "").strip() if memory_row else ""
    compacted_until_message_id = (
        memory_row.get("compacted_until_message_id") if memory_row else None
    )
    older_history, recent_history = split_recent_history(
        full_history,
        keep_turns=runtime.settings.chat_recent_turns_to_keep,
    )
    compactable_history = [
        item
        for item in older_history
        if compacted_until_message_id is None
        or _message_id(item) > int(compacted_until_message_id)
    ]
    return await runtime.db.upsert_chat_conversation_context_stats(
        conversation_id,
        last_message_id=_message_id(full_history[-1]) if full_history else None,
        compacted_until_message_id=int(compacted_until_message_id)
        if compacted_until_message_id
        else None,
        recent_start_message_id=_message_id(recent_history[0])
        if recent_history
        else None,
        memory_token_estimate=estimate_text_tokens(memory_text),
        uncompacted_token_estimate=estimate_history_tokens(compactable_history),
        recent_token_estimate=estimate_history_tokens(recent_history),
    )


async def build_conversation_context(
    runtime: Runtime,
    *,
    conversation_id: int,
) -> ConversationContext:
    stats_row = await runtime.db.get_chat_conversation_context_stats(conversation_id)
    if not stats_row:
        stats_row = await _bootstrap_context_stats(runtime, conversation_id)
    memory_row = await runtime.db.get_chat_conversation_memory(conversation_id)
    recent_history = await runtime.db.list_recent_chat_messages_by_turns(
        conversation_id,
        keep_turns=runtime.settings.chat_recent_turns_to_keep,
    )
    return _build_context_from_stats(recent_history, memory_row, stats_row)


def should_compact_context(runtime: Runtime, context: ConversationContext) -> bool:
    if context.recent_start_message_id is None:
        return False
    if context.last_message_id is None:
        return False
    if context.uncompacted_token_estimate <= 0:
        return False
    return context.estimated_tokens >= int(
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

    compactable_history = await runtime.db.list_chat_messages_between(
        conversation_id,
        start_message_id=context.compacted_until_message_id,
        end_message_id=context.recent_start_message_id,
    )
    if not compactable_history:
        await runtime.db.upsert_chat_conversation_context_stats(
            conversation_id,
            last_message_id=context.last_message_id,
            compacted_until_message_id=context.compacted_until_message_id,
            recent_start_message_id=context.recent_start_message_id,
            memory_token_estimate=context.memory_token_estimate,
            uncompacted_token_estimate=0,
            recent_token_estimate=context.recent_token_estimate,
        )
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
    await runtime.db.upsert_chat_conversation_memory(
        conversation_id,
        memory_text=memory_text,
        compacted_until_message_id=latest_message_id,
    )
    recent_history = await runtime.db.list_recent_chat_messages_by_turns(
        conversation_id,
        keep_turns=runtime.settings.chat_recent_turns_to_keep,
    )
    await runtime.db.upsert_chat_conversation_context_stats(
        conversation_id,
        last_message_id=context.last_message_id,
        compacted_until_message_id=latest_message_id,
        recent_start_message_id=_message_id(recent_history[0])
        if recent_history
        else None,
        memory_token_estimate=estimate_text_tokens(memory_text),
        uncompacted_token_estimate=0,
        recent_token_estimate=estimate_history_tokens(recent_history),
    )
    return await build_conversation_context(runtime, conversation_id=conversation_id)


async def refresh_context_stats_after_message(
    runtime: Runtime,
    *,
    conversation_id: int,
    message: dict[str, Any],
) -> dict[str, Any]:
    stats_row = await runtime.db.get_chat_conversation_context_stats(conversation_id)
    if not stats_row:
        stats_row = await _bootstrap_context_stats(runtime, conversation_id)
    memory_row = await runtime.db.get_chat_conversation_memory(conversation_id)
    compacted_until_message_id = (
        int(stats_row["compacted_until_message_id"])
        if stats_row.get("compacted_until_message_id")
        else int(memory_row["compacted_until_message_id"])
        if memory_row and memory_row.get("compacted_until_message_id")
        else None
    )
    recent_history = await runtime.db.list_recent_chat_messages_by_turns(
        conversation_id,
        keep_turns=runtime.settings.chat_recent_turns_to_keep,
    )
    recent_start_message_id = _message_id(recent_history[0]) if recent_history else None
    moved_tokens = 0
    old_recent_start = (
        int(stats_row["recent_start_message_id"])
        if stats_row.get("recent_start_message_id")
        else None
    )
    if (
        old_recent_start is not None
        and recent_start_message_id is not None
        and recent_start_message_id > old_recent_start
    ):
        moved_start_boundary = max(
            int(compacted_until_message_id or 0), old_recent_start - 1
        )
        moved_messages = await runtime.db.list_chat_messages_between(
            conversation_id,
            start_message_id=moved_start_boundary,
            end_message_id=recent_start_message_id,
        )
        moved_tokens = estimate_history_tokens(moved_messages)

    memory_text = str(memory_row.get("memory_text") or "").strip() if memory_row else ""
    updated_stats = await runtime.db.upsert_chat_conversation_context_stats(
        conversation_id,
        last_message_id=_message_id(message),
        compacted_until_message_id=compacted_until_message_id,
        recent_start_message_id=recent_start_message_id,
        memory_token_estimate=estimate_text_tokens(memory_text),
        uncompacted_token_estimate=int(stats_row.get("uncompacted_token_estimate") or 0)
        + moved_tokens,
        recent_token_estimate=estimate_history_tokens(recent_history),
    )
    return updated_stats
