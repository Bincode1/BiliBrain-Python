from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text


_CHAT_ID_LOCK = asyncio.Lock()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _conversation_scope_key(folder_id: int | None) -> str:
    scope_prefix = f"folder:{int(folder_id)}" if folder_id else "all"
    return f"{scope_prefix}:{uuid4().hex[:16]}"


async def _next_conversation_id(chat_store) -> int:
    sessions = await chat_store.list_sessions()
    max_id = max((int(item.get("conversation_id") or 0) for item in sessions), default=0)
    return max_id + 1


async def _next_message_id(chat_store) -> int:
    max_id = 0
    for session in await chat_store.list_sessions():
        conversation_id = int(session.get("conversation_id") or 0)
        for message in await chat_store.list_messages(conversation_id):
            max_id = max(max_id, int(message.get("message_id") or 0))
    return max_id + 1


def _require_chat_store(runtime):
    chat_store = getattr(runtime, "chat_store", None)
    if chat_store is None:
        require_chat_store = getattr(runtime, "require_chat_store", None)
        if callable(require_chat_store):
            return require_chat_store()
        raise RuntimeError("Chat store is not initialized.")
    return chat_store


async def get_chat_session(runtime, conversation_id: int) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.get_session(normalized_id)


async def list_chat_session_messages(
    runtime, conversation_id: int
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_messages(normalized_id)


async def list_recent_chat_session_messages(
    runtime,
    conversation_id: int,
    *,
    keep_turns: int,
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_recent_messages_by_turns(
        normalized_id,
        keep_turns=keep_turns,
    )


async def list_chat_session_messages_between(
    runtime,
    conversation_id: int,
    *,
    start_message_id: int | None = None,
    end_message_id: int | None = None,
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_messages_between(
        normalized_id,
        start_message_id=start_message_id,
        end_message_id=end_message_id,
    )


async def read_chat_session_memory(
    runtime, conversation_id: int
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.read_memory(normalized_id)


async def read_chat_session_memory_sections(
    runtime, conversation_id: int
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.read_memory_sections(normalized_id)


async def read_chat_session_context_stats(
    runtime, conversation_id: int
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.read_context_stats(normalized_id)


async def list_chat_session_tool_events(
    runtime, conversation_id: int
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.list_tool_events(normalized_id)


async def read_chat_session_pending_approval(
    runtime, conversation_id: int
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.read_pending_approval(normalized_id)


async def ensure_chat_session(
    runtime,
    *,
    conversation_id: int | None,
    folder_id: int | None,
    title: str | None = None,
) -> dict[str, Any] | None:
    if conversation_id is None:
        return await create_chat_session_dual_write(runtime, folder_id=folder_id, title=title)
    return await get_chat_session(runtime, int(conversation_id))


async def migrate_chat_storage(runtime) -> dict[str, int]:
    chat_store = _require_chat_store(runtime)
    before_sessions = await chat_store.list_sessions()
    migrated_sessions = await _migrate_legacy_chat_tables(runtime)
    await chat_store.rebuild_index()
    after_sessions = await chat_store.list_sessions()

    return {
        "file_sessions_before": len(before_sessions),
        "file_sessions_after": len(after_sessions),
        "migrated_sessions": migrated_sessions,
    }


async def _migrate_legacy_chat_tables(runtime) -> int:
    chat_store = _require_chat_store(runtime)
    db = getattr(runtime, "db", None)
    if db is None or not hasattr(db, "engine"):
        return 0

    async with db.engine.connect() as conn:
        table_result = await conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_conversations'"
            )
        )
        if table_result.first() is None:
            return 0

        conversations = (
            await conn.execute(
                text(
                    """
                    SELECT conversation_id, scope_key, folder_id, title, created_at, updated_at
                    FROM chat_conversations
                    ORDER BY updated_at DESC, conversation_id DESC
                    """
                )
            )
        ).mappings().all()

        migrated_sessions = 0
        for conversation in conversations:
            conversation_id = int(conversation["conversation_id"])
            existing = await chat_store.get_session(conversation_id)
            if existing is None:
                await chat_store.create_session(
                    conversation_id,
                    title=str(conversation.get("title") or ""),
                    folder_id=int(conversation["folder_id"]) if conversation.get("folder_id") is not None else None,
                    scope_key=str(conversation.get("scope_key") or ""),
                    created_at=str(conversation.get("created_at") or "") or None,
                    updated_at=str(conversation.get("updated_at") or "") or None,
                )
                migrated_sessions += 1

            messages = (
                await conn.execute(
                    text(
                        """
                        SELECT message_id, conversation_id, role, content, sources_json,
                               created_at, answer_mode, route_mode
                        FROM chat_messages
                        WHERE conversation_id = :conversation_id
                        ORDER BY message_id ASC
                        """
                    ),
                    {"conversation_id": conversation_id},
                )
            ).mappings().all()
            existing_message_ids = {
                int(item.get("message_id") or 0)
                for item in await chat_store.list_messages(conversation_id)
            }
            for message in messages:
                message_id = int(message["message_id"])
                if message_id in existing_message_ids:
                    continue
                sources_json = message.get("sources_json")
                await chat_store.append_message(
                    conversation_id,
                    role=str(message.get("role") or ""),
                    content=str(message.get("content") or ""),
                    sources=_parse_json_list(sources_json),
                    answer_mode=str(message.get("answer_mode") or "").strip().lower() or None,
                    route_mode=str(message.get("route_mode") or "").strip().lower() or None,
                    message_id=message_id,
                    created_at=str(message.get("created_at") or "") or None,
                    updated_at=str(message.get("created_at") or "") or None,
                )

            memory_row = (
                await conn.execute(
                    text(
                        """
                        SELECT memory_text, compacted_until_message_id
                        FROM chat_conversation_memory
                        WHERE conversation_id = :conversation_id
                        """
                    ),
                    {"conversation_id": conversation_id},
                )
            ).mappings().first()
            if memory_row is not None:
                await chat_store.write_memory(
                    conversation_id,
                    memory_text=str(memory_row.get("memory_text") or ""),
                    compacted_until_message_id=memory_row.get("compacted_until_message_id"),
                )

            stats_row = (
                await conn.execute(
                    text(
                        """
                        SELECT last_message_id, compacted_until_message_id, recent_start_message_id,
                               memory_token_estimate, uncompacted_token_estimate, recent_token_estimate
                        FROM chat_conversation_context_stats
                        WHERE conversation_id = :conversation_id
                        """
                    ),
                    {"conversation_id": conversation_id},
                )
            ).mappings().first()
            if stats_row is not None:
                await chat_store.write_context_stats(
                    conversation_id,
                    last_message_id=stats_row.get("last_message_id"),
                    compacted_until_message_id=stats_row.get("compacted_until_message_id"),
                    recent_start_message_id=stats_row.get("recent_start_message_id"),
                    memory_token_estimate=int(stats_row.get("memory_token_estimate") or 0),
                    uncompacted_token_estimate=int(stats_row.get("uncompacted_token_estimate") or 0),
                    recent_token_estimate=int(stats_row.get("recent_token_estimate") or 0),
                )

        return migrated_sessions


def _parse_json_list(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        import json

        payload = json.loads(raw)
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


async def ensure_all_chat_store_sessions_loaded(runtime) -> None:
    return None


async def ensure_chat_store_session_loaded(runtime, conversation_id: int) -> None:
    return None


async def create_chat_session_dual_write(
    runtime,
    *,
    folder_id: int | None,
    title: str | None = None,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    async with _CHAT_ID_LOCK:
        conversation_id = await _next_conversation_id(chat_store)
        now = _now_text()
        return await chat_store.create_session(
            conversation_id,
            title=title or "",
            folder_id=folder_id,
            scope_key=_conversation_scope_key(folder_id),
            created_at=now,
            updated_at=now,
        )


async def rename_chat_session_dual_write(
    runtime,
    conversation_id: int,
    title: str,
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    return await chat_store.rename_session(int(conversation_id), title)


async def delete_chat_session_dual_write(runtime, conversation_id: int) -> bool:
    chat_store = _require_chat_store(runtime)
    return await chat_store.delete_session(int(conversation_id))


async def append_chat_message_dual_write(
    runtime,
    conversation_id: int,
    role: str,
    content: str,
    *,
    sources: list[dict[str, Any]] | None = None,
    answer_mode: str | None = None,
    route_mode: str | None = None,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    async with _CHAT_ID_LOCK:
        message_id = await _next_message_id(chat_store)
        now = _now_text()
        return await chat_store.append_message(
            int(conversation_id),
            role=role,
            content=content,
            sources=sources or [],
            answer_mode=answer_mode,
            route_mode=route_mode,
            message_id=message_id,
            created_at=now,
            updated_at=now,
        )


async def replace_chat_message_dual_write(
    runtime,
    *,
    conversation_id: int,
    message_id: int,
    content: str | None = None,
    sources: list[dict[str, Any]] | None = None,
    answer_mode: str | None = None,
    route_mode: str | None = None,
) -> dict[str, Any] | None:
    chat_store = _require_chat_store(runtime)
    return await chat_store.replace_message(
        int(message_id),
        conversation_id=int(conversation_id),
        content=content,
        sources=sources,
        answer_mode=answer_mode,
        route_mode=route_mode,
    )


async def write_chat_memory_dual_write(
    runtime,
    conversation_id: int,
    *,
    memory_text: str,
    compacted_until_message_id: int | None,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    return await chat_store.write_memory(
        int(conversation_id),
        memory_text=memory_text,
        compacted_until_message_id=compacted_until_message_id,
    )


async def write_chat_memory_sections_dual_write(
    runtime,
    conversation_id: int,
    *,
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chat_store = _require_chat_store(runtime)
    return await chat_store.write_memory_sections(
        int(conversation_id),
        sections=sections,
    )


async def write_context_stats_dual_write(
    runtime,
    conversation_id: int,
    *,
    last_message_id: int | None,
    compacted_until_message_id: int | None,
    recent_start_message_id: int | None,
    memory_token_estimate: int,
    uncompacted_token_estimate: int,
    recent_token_estimate: int,
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    return await chat_store.write_context_stats(
        int(conversation_id),
        last_message_id=last_message_id,
        compacted_until_message_id=compacted_until_message_id,
        recent_start_message_id=recent_start_message_id,
        memory_token_estimate=memory_token_estimate,
        uncompacted_token_estimate=uncompacted_token_estimate,
        recent_token_estimate=recent_token_estimate,
    )


async def append_chat_tool_event(
    runtime,
    conversation_id: int,
    *,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    chat_store = _require_chat_store(runtime)
    event_payload = dict(payload or {})
    event_payload["event_type"] = str(event_type or "").strip().lower()
    await chat_store.append_tool_event(int(conversation_id), event_payload)


async def write_chat_pending_approval(
    runtime,
    conversation_id: int,
    *,
    payload: dict[str, Any],
) -> dict[str, Any]:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    return await chat_store.write_pending_approval(normalized_id, payload)


async def clear_chat_pending_approval(runtime, conversation_id: int) -> None:
    chat_store = _require_chat_store(runtime)
    normalized_id = int(conversation_id)
    await chat_store.clear_pending_approval(normalized_id)
