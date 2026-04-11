from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, insert, update, delete, func, and_

from bilibrain.db.tables import ingestion_batches, ingestion_tasks
from bilibrain.db.database import _format_datetime


async def create_ingestion_batch(
    self,
    *,
    batch_type: str = "video_batch",
    title: str | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options_json = json.dumps(options, ensure_ascii=False) if options else None
    async with self.engine.begin() as conn:
        result = await conn.execute(
            insert(ingestion_batches).values(
                batch_type=batch_type,
                title=title,
                options_json=options_json,
            )
        )
        batch_id = result.inserted_primary_key[0]
    return await self.get_ingestion_batch(batch_id)


async def get_ingestion_batch(self, batch_id: int) -> dict[str, Any] | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(ingestion_batches).where(ingestion_batches.c.batch_id == batch_id)
        )
        row = result.mappings().first()
    if row is None:
        return None
    return self._format_ingestion_batch(dict(row))


async def list_ingestion_batches(self, *, limit: int = 50) -> list[dict[str, Any]]:
    stmt = (
        select(ingestion_batches)
        .order_by(ingestion_batches.c.batch_id.desc())
        .limit(limit)
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    return [self._format_ingestion_batch(dict(row)) for row in rows]


async def create_ingestion_task(
    self,
    *,
    bvid: str,
    batch_id: int | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing = await self.get_active_ingestion_task_for_bvid(bvid)
    if existing is not None:
        return existing
    options_json = json.dumps(options, ensure_ascii=False) if options else None
    async with self.engine.begin() as conn:
        result = await conn.execute(
            insert(ingestion_tasks).values(
                batch_id=batch_id,
                bvid=bvid,
                options_json=options_json,
            )
        )
        task_id = result.inserted_primary_key[0]
    return await self.get_ingestion_task(task_id)


async def list_ingestion_tasks(
    self,
    *,
    batch_id: int | None = None,
    statuses: list[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stmt = (
        select(ingestion_tasks).order_by(ingestion_tasks.c.task_id.desc()).limit(limit)
    )
    conditions: list = []
    if batch_id is not None:
        conditions.append(ingestion_tasks.c.batch_id == batch_id)
    if statuses:
        conditions.append(ingestion_tasks.c.status.in_(statuses))
    if conditions:
        stmt = stmt.where(and_(*conditions))
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    return [self._format_ingestion_task(dict(row)) for row in rows]


async def get_ingestion_task(self, task_id: int) -> dict[str, Any] | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(ingestion_tasks).where(ingestion_tasks.c.task_id == task_id)
        )
        row = result.mappings().first()
    if row is None:
        return None
    return self._format_ingestion_task(dict(row))


async def get_active_ingestion_task_for_bvid(self, bvid: str) -> dict[str, Any] | None:
    stmt = (
        select(ingestion_tasks)
        .where(
            ingestion_tasks.c.bvid == bvid,
            ingestion_tasks.c.status.in_(["queued", "running"]),
        )
        .order_by(ingestion_tasks.c.task_id.desc())
        .limit(1)
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        row = result.mappings().first()
    if row is None:
        return None
    return self._format_ingestion_task(dict(row))


async def claim_next_ingestion_task(
    self,
    *,
    worker_id: str,
    stale_after_seconds: int = 1800,
) -> dict[str, Any] | None:
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(seconds=stale_after_seconds)

    locked = ingestion_tasks.alias("locked")
    find_stmt = (
        select(ingestion_tasks.c.task_id)
        .select_from(
            ingestion_tasks.outerjoin(
                locked,
                and_(
                    locked.c.bvid == ingestion_tasks.c.bvid,
                    locked.c.status == "running",
                    locked.c.locked_at >= stale_cutoff,
                    locked.c.task_id != ingestion_tasks.c.task_id,
                ),
            )
        )
        .where(
            ingestion_tasks.c.status == "queued",
            locked.c.task_id.is_(None),
        )
        .order_by(ingestion_tasks.c.task_id.asc())
        .limit(1)
    )

    async with self.engine.begin() as conn:
        result = await conn.execute(find_stmt)
        candidate = result.mappings().first()
        if candidate is None:
            return None
        task_id = int(candidate["task_id"])

        await conn.execute(
            update(ingestion_tasks)
            .where(ingestion_tasks.c.task_id == task_id)
            .values(
                status="running",
                worker_id=worker_id,
                locked_at=now,
                started_at=func.coalesce(ingestion_tasks.c.started_at, now),
                attempt_count=ingestion_tasks.c.attempt_count + 1,
                updated_at=now,
            )
        )

        result = await conn.execute(
            select(ingestion_tasks).where(ingestion_tasks.c.task_id == task_id)
        )
        row = result.mappings().first()

    if row is None:
        return None
    return self._format_ingestion_task(dict(row))


async def mark_ingestion_task_succeeded(self, task_id: int) -> dict[str, Any] | None:
    now = datetime.utcnow()
    async with self.engine.begin() as conn:
        await conn.execute(
            update(ingestion_tasks)
            .where(ingestion_tasks.c.task_id == task_id)
            .values(
                status="succeeded",
                finished_at=now,
                updated_at=now,
            )
        )
    return await self.get_ingestion_task(task_id)


async def mark_ingestion_task_failed(
    self, task_id: int, error: str
) -> dict[str, Any] | None:
    now = datetime.utcnow()
    async with self.engine.begin() as conn:
        await conn.execute(
            update(ingestion_tasks)
            .where(ingestion_tasks.c.task_id == task_id)
            .values(
                status="failed",
                last_error=error,
                finished_at=now,
                updated_at=now,
            )
        )
    return await self.get_ingestion_task(task_id)


async def mark_ingestion_task_stale(self, task_id: int) -> dict[str, Any] | None:
    now = datetime.utcnow()
    async with self.engine.begin() as conn:
        await conn.execute(
            update(ingestion_tasks)
            .where(ingestion_tasks.c.task_id == task_id)
            .values(
                status="stale",
                worker_id=None,
                locked_at=None,
                updated_at=now,
            )
        )
    return await self.get_ingestion_task(task_id)


async def touch_ingestion_task_lock(
    self, task_id: int, *, worker_id: str | None = None
) -> dict[str, Any] | None:
    now = datetime.utcnow()
    values: dict[str, Any] = {
        "locked_at": now,
        "updated_at": now,
    }
    if worker_id is not None:
        values["worker_id"] = worker_id
    async with self.engine.begin() as conn:
        await conn.execute(
            update(ingestion_tasks)
            .where(ingestion_tasks.c.task_id == task_id)
            .values(**values)
        )
    return await self.get_ingestion_task(task_id)


async def mark_stale_ingestion_tasks(
    self,
    *,
    stale_after_seconds: int = 1800,
    limit: int = 100,
) -> list[dict[str, Any]]:
    stale_cutoff = datetime.utcnow() - timedelta(seconds=stale_after_seconds)
    stmt = (
        select(ingestion_tasks.c.task_id)
        .where(
            ingestion_tasks.c.status == "running",
            ingestion_tasks.c.locked_at < stale_cutoff,
        )
        .order_by(ingestion_tasks.c.task_id.asc())
        .limit(limit)
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        task_id = int(row["task_id"])
        task = await self.mark_ingestion_task_stale(task_id)
        if task is not None:
            items.append(task)
    return items


async def cancel_ingestion_task(self, task_id: int) -> dict[str, Any] | None:
    now = datetime.utcnow()
    async with self.engine.begin() as conn:
        await conn.execute(
            update(ingestion_tasks)
            .where(ingestion_tasks.c.task_id == task_id)
            .values(
                status="cancelled",
                finished_at=now,
                updated_at=now,
            )
        )
    return await self.get_ingestion_task(task_id)


async def delete_ingestion_tasks_for_bvid(self, bvid: str) -> int:
    async with self.engine.begin() as conn:
        result = await conn.execute(
            delete(ingestion_tasks).where(ingestion_tasks.c.bvid == bvid)
        )
    return result.rowcount


async def delete_all_ingestion_tasks(self) -> int:
    async with self.engine.begin() as conn:
        result = await conn.execute(ingestion_tasks.delete())
    return result.rowcount
