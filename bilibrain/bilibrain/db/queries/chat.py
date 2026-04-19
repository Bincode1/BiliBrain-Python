from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, insert, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from bilibrain.db.tables import (
    tool_workspaces,
    tool_calls,
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
    return await self.ensure_default_tool_workspace(actor=actor)


async def ensure_default_tool_workspace(self, actor: str = "system") -> dict[str, Any]:
    scope_key = "workspace:default"
    async with self.engine.begin() as conn:
        default_row = (
            await conn.execute(
                select(tool_workspaces).where(tool_workspaces.c.workspace_id == "default")
            )
        ).mappings().first()

        await conn.execute(
            tool_calls.update()
            .where(tool_calls.c.workspace_id != "default")
            .values(workspace_id="default")
        )

        if default_row is None:
            await conn.execute(
                sqlite_insert(tool_workspaces).values(
                    workspace_id="default",
                    scope_key=scope_key,
                    feature_name="workspace",
                    conversation_id=None,
                    title="Default Workspace",
                    actor=actor,
                )
            )
        else:
            await conn.execute(
                tool_workspaces.update()
                .where(tool_workspaces.c.workspace_id == "default")
                .values(
                    scope_key=scope_key,
                    feature_name="workspace",
                    conversation_id=None,
                    title="Default Workspace",
                    actor=actor,
                )
            )
        await conn.execute(
            tool_workspaces.delete().where(tool_workspaces.c.workspace_id != "default")
        )

    row = await self.get_tool_workspace("default")
    if row is None:
        raise RuntimeError("Failed to ensure default workspace.")
    return row


async def get_tool_workspace_by_scope_key(
    self, scope_key: str
) -> dict[str, Any] | None:
    if str(scope_key or "").strip() != "workspace:default":
        return None
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(tool_workspaces).where(tool_workspaces.c.workspace_id == "default")
        )
        row = result.mappings().first()
    if row is None:
        return None
    d = dict(row)
    d["created_at"] = _format_datetime(d.get("created_at"))
    d["updated_at"] = _format_datetime(d.get("updated_at"))
    return d


async def get_tool_workspace(self, workspace_id: str) -> dict[str, Any] | None:
    if str(workspace_id or "").strip() != "default":
        return None
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(tool_workspaces).where(
                tool_workspaces.c.workspace_id == "default"
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
    if feature_name and str(feature_name).strip() != "workspace":
        return []
    stmt = select(tool_workspaces).where(tool_workspaces.c.workspace_id == "default").limit(1)
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
# Tool calls for conversation
# ---------------------------------------------------------------------------


async def list_tool_calls_for_conversation(
    self,
    conversation_id: int,
) -> list[dict[str, Any]]:
    return []


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
