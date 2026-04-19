from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, func, delete, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from bilibrain.db.tables import app_state


async def save_state(self: Any, key: str, value: dict[str, Any]) -> None:
    stmt = sqlite_insert(app_state).values(
        state_key=key,
        state_value=json.dumps(value, ensure_ascii=False),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["state_key"],
        set_={"state_value": stmt.excluded.state_value},
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)


async def load_state(self: Any, key: str) -> dict[str, Any] | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(app_state.c.state_value).where(app_state.c.state_key == key)
        )
        row = result.mappings().first()
    if row is None:
        return None
    return json.loads(row["state_value"])


async def get_state_updated_at(self: Any, key: str) -> datetime | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(app_state.c.updated_at).where(app_state.c.state_key == key)
        )
        return result.scalar_one_or_none()


async def get_processing_settings(self: Any) -> dict[str, int]:
    stored = await self.load_state("processing_settings") or {}
    return {
        "max_video_minutes": max(
            int(
                stored.get("max_video_minutes")
                or self.settings.default_max_video_minutes
            ),
            1,
        ),
    }


async def save_processing_settings(
    self: Any, *, max_video_minutes: int
) -> dict[str, int]:
    payload: dict[str, int] = {"max_video_minutes": max_video_minutes}
    await self.save_state("processing_settings", payload)
    return payload


async def try_acquire_state_lease(
    self: Any,
    *,
    key: str,
    owner: str,
    lease_seconds: int = 60,
) -> bool:
    now = datetime.utcnow()
    stale_before = now - timedelta(seconds=max(int(lease_seconds), 1))
    async with self.engine.connect() as conn:
        await conn.execute(text("BEGIN IMMEDIATE"))
        try:
            result = await conn.execute(
                select(app_state.c.state_value, app_state.c.updated_at).where(
                    app_state.c.state_key == key
                )
            )
            row = result.mappings().first()
            if row is not None:
                current_value = row.get("state_value") or ""
                try:
                    current_payload = json.loads(current_value)
                except json.JSONDecodeError:
                    current_payload = {}
                current_owner = str(current_payload.get("owner") or "").strip()
                current_updated_at = row.get("updated_at")
                if current_owner and current_owner != owner and current_updated_at is not None:
                    if current_updated_at >= stale_before:
                        await conn.rollback()
                        return False
            payload = {"owner": owner}
            stmt = sqlite_insert(app_state).values(
                state_key=key,
                state_value=json.dumps(payload, ensure_ascii=False),
                updated_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["state_key"],
                set_={
                    "state_value": stmt.excluded.state_value,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await conn.execute(stmt)
            await conn.commit()
            return True
        except Exception:
            await conn.rollback()
            raise


async def release_state_lease(
    self: Any,
    *,
    key: str,
    owner: str,
) -> None:
    async with self.engine.begin() as conn:
        result = await conn.execute(
            select(app_state.c.state_value).where(app_state.c.state_key == key)
        )
        row = result.mappings().first()
        if row is None:
            return
        try:
            payload = json.loads(row.get("state_value") or "")
        except json.JSONDecodeError:
            payload = {}
        if str(payload.get("owner") or "").strip() != owner:
            return
        await conn.execute(delete(app_state).where(app_state.c.state_key == key))
