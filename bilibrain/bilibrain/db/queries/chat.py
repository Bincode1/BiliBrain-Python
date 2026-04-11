from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, insert, update, delete, func, and_, or_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from bilibrain.db.tables import (
    tool_workspaces,
    tool_calls,
    chat_conversations,
    chat_messages,
    chat_conversation_memory,
    chat_conversation_context_stats,
    folders,
    videos,
    video_pipeline,
)
from bilibrain.db.database import _format_datetime


# ---------------------------------------------------------------------------
# Tool workspace functions
# ---------------------------------------------------------------------------


async def create_tool_workspace(
    self,
    *,
    workspace_id: str,
    scope_key: str,
    feature_name: str,
    conversation_id: int | None = None,
    title: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    existing = await self.get_tool_workspace_by_scope_key(scope_key)
    if existing:
        return existing
    stmt = sqlite_insert(tool_workspaces).values(
        workspace_id=workspace_id,
        scope_key=scope_key,
        feature_name=feature_name,
        conversation_id=conversation_id,
        title=title,
        actor=actor,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["workspace_id"],
        set_={
            "feature_name": stmt.excluded.feature_name,
            "conversation_id": stmt.excluded.conversation_id,
            "title": stmt.excluded.title,
            "actor": stmt.excluded.actor,
        },
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(tool_workspaces).where(
                tool_workspaces.c.workspace_id == workspace_id
            )
        )
        row = result.mappings().first()
    if row is None:
        return {
            "workspace_id": workspace_id,
            "scope_key": scope_key,
            "feature_name": feature_name,
            "conversation_id": conversation_id,
            "title": title,
            "actor": actor,
            "status": "active",
            "created_at": None,
            "updated_at": None,
        }
    d = dict(row)
    d["created_at"] = _format_datetime(d.get("created_at"))
    d["updated_at"] = _format_datetime(d.get("updated_at"))
    return d


async def get_tool_workspace_by_scope_key(
    self, scope_key: str
) -> dict[str, Any] | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(tool_workspaces).where(tool_workspaces.c.scope_key == scope_key)
        )
        row = result.mappings().first()
    if row is None:
        return None
    d = dict(row)
    d["created_at"] = _format_datetime(d.get("created_at"))
    d["updated_at"] = _format_datetime(d.get("updated_at"))
    return d


async def get_tool_workspace(self, workspace_id: str) -> dict[str, Any] | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(tool_workspaces).where(
                tool_workspaces.c.workspace_id == workspace_id
            )
        )
        row = result.mappings().first()
    if row is None:
        return None
    d = dict(row)
    d["created_at"] = _format_datetime(d.get("created_at"))
    d["updated_at"] = _format_datetime(d.get("updated_at"))
    return d


async def list_tool_workspaces(
    self, *, feature_name: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    stmt = (
        select(tool_workspaces)
        .order_by(tool_workspaces.c.created_at.desc())
        .limit(limit)
    )
    if feature_name:
        stmt = stmt.where(tool_workspaces.c.feature_name == feature_name)
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["created_at"] = _format_datetime(d.get("created_at"))
        d["updated_at"] = _format_datetime(d.get("updated_at"))
        items.append(d)
    return items


async def log_tool_call(
    self,
    *,
    trace_id: str,
    workspace_id: str,
    tool_name: str,
    actor: str,
    approval_mode: str,
    status: str,
    arguments: dict[str, Any],
    result: Any = None,
    error: str | None = None,
    duration_ms: float = 0.0,
) -> dict[str, Any]:
    async with self.engine.begin() as conn:
        res = await conn.execute(
            insert(tool_calls).values(
                trace_id=trace_id,
                workspace_id=workspace_id,
                tool_name=tool_name,
                status=status,
                arguments_json=json.dumps(arguments, ensure_ascii=False),
                result_json=json.dumps(result, ensure_ascii=False)
                if result is not None
                else None,
                error_json=json.dumps(error, ensure_ascii=False)
                if error is not None
                else None,
                duration_ms=duration_ms,
                actor=actor,
                approval_mode=approval_mode,
            )
        )
        call_id = res.inserted_primary_key[0]
    async with self.engine.connect() as conn:
        res2 = await conn.execute(
            select(tool_calls).where(tool_calls.c.call_id == call_id)
        )
        row = res2.mappings().first()
    if row is None:
        return {"call_id": call_id}
    return self._format_tool_call(dict(row))


# ---------------------------------------------------------------------------
# Chat conversation functions
# ---------------------------------------------------------------------------


async def get_chat_conversation(self, conversation_id: int) -> dict[str, Any] | None:
    message_count_sub = (
        select(func.count())
        .select_from(chat_messages)
        .where(chat_messages.c.conversation_id == conversation_id)
        .correlate(chat_conversations)
        .scalar_subquery()
        .label("message_count")
    )
    stmt = select(chat_conversations, message_count_sub).where(
        chat_conversations.c.conversation_id == conversation_id
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        row = result.mappings().first()
    if row is None:
        return None
    return self._format_chat_conversation(dict(row))


async def create_chat_conversation(
    self, folder_id: int | None, *, title: str | None = None
) -> dict[str, Any]:
    scope_key = self._conversation_scope_key(folder_id)
    normalized_title = self._normalize_chat_title(title)
    async with self.engine.begin() as conn:
        res = await conn.execute(
            insert(chat_conversations).values(
                scope_key=scope_key,
                folder_id=folder_id,
                title=normalized_title,
            )
        )
        conversation_id = res.inserted_primary_key[0]
    return await self.get_chat_conversation(conversation_id)


def _build_conversation_list_query(
    *, folder_id: int | None, all_scopes: bool, limit: int | None = None
):
    message_count_sub = (
        select(func.count())
        .select_from(chat_messages)
        .where(chat_messages.c.conversation_id == chat_conversations.c.conversation_id)
        .correlate(chat_conversations)
        .scalar_subquery()
        .label("message_count")
    )
    stmt = select(chat_conversations, message_count_sub)
    if all_scopes:
        pass
    elif folder_id is not None:
        stmt = stmt.where(chat_conversations.c.folder_id == folder_id)
    else:
        stmt = stmt.where(chat_conversations.c.scope_key.like("all:%"))
    stmt = stmt.order_by(chat_conversations.c.updated_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    return stmt


async def get_latest_chat_conversation(
    self, folder_id: int | None, *, all_scopes: bool = False
) -> dict[str, Any] | None:
    stmt = _build_conversation_list_query(
        folder_id=folder_id, all_scopes=all_scopes, limit=1
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        row = result.mappings().first()
    if row is None:
        return None
    return self._format_chat_conversation(dict(row))


async def list_chat_conversations(
    self, folder_id: int | None, *, all_scopes: bool = False
) -> list[dict[str, Any]]:
    stmt = _build_conversation_list_query(folder_id=folder_id, all_scopes=all_scopes)
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    return [self._format_chat_conversation(dict(row)) for row in rows]


async def delete_chat_conversation(self, conversation_id: int) -> bool:
    existing = await self.get_chat_conversation(conversation_id)
    if existing is None:
        return False
    async with self.engine.begin() as conn:
        await conn.execute(
            delete(chat_messages).where(
                chat_messages.c.conversation_id == conversation_id
            )
        )
        await conn.execute(
            delete(chat_conversation_memory).where(
                chat_conversation_memory.c.conversation_id == conversation_id
            )
        )
        await conn.execute(
            delete(chat_conversation_context_stats).where(
                chat_conversation_context_stats.c.conversation_id == conversation_id
            )
        )
        await conn.execute(
            delete(chat_conversations).where(
                chat_conversations.c.conversation_id == conversation_id
            )
        )
    return True


async def rename_chat_conversation(
    self, conversation_id: int, title: str
) -> dict[str, Any] | None:
    normalized_title = self._normalize_chat_title(title)
    stmt = (
        update(chat_conversations)
        .where(chat_conversations.c.conversation_id == conversation_id)
        .values(title=normalized_title)
    )
    async with self.engine.begin() as conn:
        result = await conn.execute(stmt)
        if result.rowcount == 0:
            return None
    return await self.get_chat_conversation(conversation_id)


# ---------------------------------------------------------------------------
# Chat conversation memory functions
# ---------------------------------------------------------------------------


async def get_chat_conversation_memory(
    self, conversation_id: int
) -> dict[str, Any] | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(chat_conversation_memory).where(
                chat_conversation_memory.c.conversation_id == conversation_id
            )
        )
        row = result.mappings().first()
    if row is None:
        return None
    return self._format_chat_memory(dict(row))


async def upsert_chat_conversation_memory(
    self,
    conversation_id: int,
    *,
    memory_text: str,
    compacted_until_message_id: int,
) -> dict[str, Any]:
    stmt = sqlite_insert(chat_conversation_memory).values(
        conversation_id=conversation_id,
        memory_text=memory_text,
        compacted_until_message_id=compacted_until_message_id,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["conversation_id"],
        set_={
            "memory_text": stmt.excluded.memory_text,
            "compacted_until_message_id": stmt.excluded.compacted_until_message_id,
        },
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)
    return await self.get_chat_conversation_memory(conversation_id)


# ---------------------------------------------------------------------------
# Chat conversation context stats functions
# ---------------------------------------------------------------------------


async def get_chat_conversation_context_stats(
    self, conversation_id: int
) -> dict[str, Any] | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(chat_conversation_context_stats).where(
                chat_conversation_context_stats.c.conversation_id == conversation_id
            )
        )
        row = result.mappings().first()
    if row is None:
        return None
    return self._format_chat_context_stats(dict(row))


async def upsert_chat_conversation_context_stats(
    self,
    conversation_id: int,
    *,
    last_message_id: int,
    compacted_until_message_id: int,
    recent_start_message_id: int,
    memory_token_estimate: int,
    uncompacted_token_estimate: int,
    recent_token_estimate: int,
) -> dict[str, Any]:
    stmt = sqlite_insert(chat_conversation_context_stats).values(
        conversation_id=conversation_id,
        last_message_id=last_message_id,
        compacted_until_message_id=compacted_until_message_id,
        recent_start_message_id=recent_start_message_id,
        memory_token_estimate=memory_token_estimate,
        uncompacted_token_estimate=uncompacted_token_estimate,
        recent_token_estimate=recent_token_estimate,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["conversation_id"],
        set_={
            "last_message_id": stmt.excluded.last_message_id,
            "compacted_until_message_id": stmt.excluded.compacted_until_message_id,
            "recent_start_message_id": stmt.excluded.recent_start_message_id,
            "memory_token_estimate": stmt.excluded.memory_token_estimate,
            "uncompacted_token_estimate": stmt.excluded.uncompacted_token_estimate,
            "recent_token_estimate": stmt.excluded.recent_token_estimate,
        },
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)
    return await self.get_chat_conversation_context_stats(conversation_id)


# ---------------------------------------------------------------------------
# Chat message functions
# ---------------------------------------------------------------------------


async def list_chat_messages(
    self, conversation_id: int, *, limit: int | None = None
) -> list[dict[str, Any]]:
    stmt = (
        select(chat_messages)
        .where(chat_messages.c.conversation_id == conversation_id)
        .order_by(chat_messages.c.message_id.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    return [self._format_chat_message(dict(row)) for row in rows]


async def list_recent_chat_messages_by_turns(
    self, conversation_id: int, *, keep_turns: int
) -> list[dict[str, Any]]:
    stmt = (
        select(chat_messages)
        .where(chat_messages.c.conversation_id == conversation_id)
        .order_by(chat_messages.c.message_id.desc())
        .limit(500)
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    all_messages: list[dict[str, Any]] = []
    for row in rows:
        all_messages.append(self._format_chat_message(dict(row)))
    user_turns = 0
    kept: list[dict[str, Any]] = []
    for msg in all_messages:
        if msg["role"] == "user":
            user_turns += 1
        if user_turns > keep_turns:
            break
        kept.append(msg)
    kept.reverse()
    return kept


async def list_chat_messages_between(
    self,
    conversation_id: int,
    *,
    start_message_id: int | None = None,
    end_message_id: int | None = None,
) -> list[dict[str, Any]]:
    conditions = [chat_messages.c.conversation_id == conversation_id]
    if start_message_id is not None:
        conditions.append(chat_messages.c.message_id >= start_message_id)
    if end_message_id is not None:
        conditions.append(chat_messages.c.message_id <= end_message_id)
    stmt = (
        select(chat_messages)
        .where(and_(*conditions))
        .order_by(chat_messages.c.message_id.asc())
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    return [self._format_chat_message(dict(row)) for row in rows]


async def append_chat_message(
    self,
    conversation_id: int,
    role: str,
    content: str,
    *,
    sources: list[dict[str, Any]] | None = None,
    answer_mode: str | None = None,
    route_mode: str | None = None,
) -> dict[str, Any]:
    sources_json_str = json.dumps(sources, ensure_ascii=False) if sources else None
    async with self.engine.begin() as conn:
        res = await conn.execute(
            insert(chat_messages).values(
                conversation_id=conversation_id,
                role=role,
                content=content,
                sources_json=sources_json_str,
                answer_mode=answer_mode,
                route_mode=route_mode,
            )
        )
        message_id = res.inserted_primary_key[0]
        await conn.execute(
            update(chat_conversations)
            .where(chat_conversations.c.conversation_id == conversation_id)
            .values(updated_at=datetime.utcnow())
        )
        if role == "user":
            count_res = await conn.execute(
                select(func.count())
                .select_from(chat_messages)
                .where(
                    chat_messages.c.conversation_id == conversation_id,
                    chat_messages.c.role == "user",
                )
            )
            count = count_res.scalar()
            if count == 1:
                auto_title = self._build_chat_title(content)
                await conn.execute(
                    update(chat_conversations)
                    .where(
                        chat_conversations.c.conversation_id == conversation_id,
                        or_(
                            chat_conversations.c.title.is_(None),
                            chat_conversations.c.title == "",
                        ),
                    )
                    .values(title=auto_title)
                )
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(chat_messages).where(chat_messages.c.message_id == message_id)
        )
        row = result.mappings().first()
    if row is None:
        return {"message_id": message_id}
    return self._format_chat_message(dict(row))


async def update_chat_message(
    self,
    message_id: int,
    *,
    content: str | None = None,
    sources: list[dict[str, Any]] | None = None,
    answer_mode: str | None = None,
    route_mode: str | None = None,
) -> dict[str, Any] | None:
    values: dict[str, Any] = {}
    if content is not None:
        values["content"] = content
    if sources is not None:
        values["sources_json"] = json.dumps(sources, ensure_ascii=False)
    if answer_mode is not None:
        values["answer_mode"] = answer_mode
    if route_mode is not None:
        values["route_mode"] = route_mode
    if not values:
        return None
    async with self.engine.begin() as conn:
        await conn.execute(
            update(chat_messages)
            .where(chat_messages.c.message_id == message_id)
            .values(**values)
        )
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(chat_messages).where(chat_messages.c.message_id == message_id)
        )
        row = result.mappings().first()
    return self._format_chat_message(dict(row)) if row else None


# ---------------------------------------------------------------------------
# Tool calls for conversation
# ---------------------------------------------------------------------------


async def list_tool_calls_for_conversation(
    self,
    conversation_id: int,
) -> list[dict[str, Any]]:
    """Return tool_calls rows for all workspaces belonging to a conversation."""
    stmt = (
        select(tool_calls)
        .where(
            tool_calls.c.workspace_id.in_(
                select(tool_workspaces.c.workspace_id).where(
                    tool_workspaces.c.conversation_id == conversation_id
                )
            )
        )
        .order_by(tool_calls.c.call_id.asc())
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    return [self._format_tool_call(dict(row)) for row in rows]


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------


async def get_counts(self) -> dict[str, int]:
    async with self.engine.connect() as conn:
        folder_count = (
            await conn.execute(select(func.count()).select_from(folders))
        ).scalar()
        video_count = (
            await conn.execute(select(func.count()).select_from(videos))
        ).scalar()
        pipeline_count = (
            await conn.execute(select(func.count()).select_from(video_pipeline))
        ).scalar()
    return {
        "folders": int(folder_count or 0),
        "videos": int(video_count or 0),
        "video_pipeline": int(pipeline_count or 0),
    }
