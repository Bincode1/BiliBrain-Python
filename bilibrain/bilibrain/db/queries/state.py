from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, func
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
