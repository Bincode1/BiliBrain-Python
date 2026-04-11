from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, update, delete, func, case, and_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from bilibrain.db.tables import (
    folders,
    videos,
    transcripts as transcripts_tbl,
    video_summaries,
    video_pipeline,
    ingestion_tasks,
)
from bilibrain.db.database import _format_datetime
from bilibrain.services.common import (
    parse_manual_tags,
    pipeline_error_message,
    pipeline_overall_status,
)


async def save_folders(
    self, uid: int, folders_data: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = [
        {
            "folder_id": f["folder_id"],
            "uid": uid,
            "title": f.get("title", ""),
            "media_count": f.get("media_count", 0),
        }
        for f in folders_data
    ]
    stmt = sqlite_insert(folders).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["folder_id"],
        set_={
            "title": stmt.excluded.title,
            "media_count": stmt.excluded.media_count,
            "uid": stmt.excluded.uid,
        },
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)
    return await self.get_folders_by_uid(uid)


async def get_folders_by_uid(self, uid: int) -> list[dict[str, Any]]:
    stmt = (
        select(
            folders.c.folder_id,
            folders.c.title,
            folders.c.media_count,
            folders.c.updated_at,
            func.coalesce(
                func.sum(
                    case(
                        (
                            video_pipeline.c.overall_status == "indexed",
                            video_pipeline.c.index_chunk_count,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("synced_chunk_count"),
            func.coalesce(
                func.sum(
                    case(
                        (video_pipeline.c.overall_status == "indexed", 1),
                        else_=0,
                    )
                ),
                0,
            ).label("synced_videos"),
        )
        .select_from(
            folders.outerjoin(
                videos, videos.c.folder_id == folders.c.folder_id
            ).outerjoin(video_pipeline, video_pipeline.c.bvid == videos.c.bvid)
        )
        .where(folders.c.uid == uid)
        .group_by(
            folders.c.folder_id,
            folders.c.title,
            folders.c.media_count,
            folders.c.updated_at,
        )
        .order_by(folders.c.media_count.desc())
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["updated_at"] = _format_datetime(d.get("updated_at"))
        items.append(d)
    return items


async def get_folder(self, folder_id: int) -> dict[str, Any] | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(folders).where(folders.c.folder_id == folder_id)
        )
        row = result.mappings().first()
    return dict(row) if row else None


async def get_video_records(self, folder_id: int) -> list[dict[str, Any]]:
    stmt = (
        select(
            videos,
            transcripts_tbl.c.source_model.label("transcript_source"),
            transcripts_tbl.c.segment_count,
            transcripts_tbl.c.updated_at.label("transcript_updated_at"),
            video_summaries.c.updated_at.label("summary_updated_at"),
            video_pipeline.c.state_json,
        )
        .select_from(
            videos.outerjoin(transcripts_tbl, transcripts_tbl.c.bvid == videos.c.bvid)
            .outerjoin(video_summaries, video_summaries.c.bvid == videos.c.bvid)
            .outerjoin(video_pipeline, video_pipeline.c.bvid == videos.c.bvid)
        )
        .where(videos.c.folder_id == folder_id)
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        state = self._hydrate_pipeline_state(
            bvid=d["bvid"],
            raw_state_json=d.get("state_json"),
            transcript_source=d.get("transcript_source"),
            transcript_segment_count=d.get("segment_count"),
            transcript_updated_at=d.get("transcript_updated_at"),
            audio_storage_provider=d.get("audio_storage_provider"),
            audio_object_key=d.get("audio_object_key"),
            audio_uploaded_at=d.get("audio_uploaded_at"),
            synced_at=d.get("synced_at"),
        )
        items.append(
            {
                "bvid": d["bvid"],
                "folder_id": d["folder_id"],
                "title": d.get("title") or "",
                "up_name": d.get("up_name"),
                "cover_url": d.get("cover_url"),
                "duration": int(d.get("duration") or 0),
                "published_at": _format_datetime(d.get("published_at")),
                "manual_tags": parse_manual_tags(d.get("manual_tags")),
                "is_invalid": bool(d.get("is_invalid")),
                "has_summary": d.get("summary_updated_at") is not None,
                "transcript_source": state["transcript"].get("source_model"),
                "transcript_segment_count": int(
                    state["transcript"].get("segment_count") or 0
                ),
                "transcript_updated_at": _format_datetime(
                    state["transcript"].get("updated_at")
                ),
                "sync_status": pipeline_overall_status(state),
                "chunk_count": int(state["index"].get("count") or 0),
                "pipeline": state,
                "synced_at": _format_datetime(d.get("synced_at")),
                "error_msg": pipeline_error_message(state),
                "created_at": _format_datetime(d.get("created_at")),
            }
        )
    return items


async def get_video(self, bvid: str) -> dict[str, Any] | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(select(videos).where(videos.c.bvid == bvid))
        row = result.mappings().first()
    if row is None:
        return None
    d = dict(row)
    d["manual_tags"] = parse_manual_tags(d.get("manual_tags"))
    d["is_invalid"] = bool(d.get("is_invalid"))
    d["audio_storage_provider"] = d.get("audio_storage_provider")
    d["audio_object_key"] = d.get("audio_object_key")
    d["audio_uploaded_at"] = _format_datetime(d.get("audio_uploaded_at"))
    d["published_at"] = _format_datetime(d.get("published_at"))
    d["synced_at"] = _format_datetime(d.get("synced_at"))
    return d


async def upsert_video(self, video: dict[str, Any]) -> None:
    stmt = sqlite_insert(videos).values(
        bvid=video["bvid"],
        folder_id=video["folder_id"],
        title=video.get("title", ""),
        up_name=video.get("up_name"),
        cover_url=video.get("cover_url"),
        duration=video.get("duration", 0),
        published_at=video.get("published_at"),
        cid=video.get("cid"),
        subtitle_source=video.get("subtitle_source"),
        manual_tags=video.get("manual_tags"),
        synced_at=video.get("synced_at"),
        audio_storage_provider=video.get("audio_storage_provider"),
        audio_object_key=video.get("audio_object_key"),
        audio_uploaded_at=video.get("audio_uploaded_at"),
        is_invalid=video.get("is_invalid", 0),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["bvid"],
        set_={
            "folder_id": stmt.excluded.folder_id,
            "title": stmt.excluded.title,
            "up_name": stmt.excluded.up_name,
            "cover_url": stmt.excluded.cover_url,
            "duration": stmt.excluded.duration,
            "published_at": stmt.excluded.published_at,
        },
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)


async def set_video_tags(self, bvid: str, tags: list[str]) -> list[str]:
    stmt = (
        update(videos)
        .where(videos.c.bvid == bvid)
        .values(manual_tags=json.dumps(tags, ensure_ascii=False))
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)
    return tags


async def mark_video_processed(
    self,
    *,
    bvid: str,
    cid: int | None,
    transcript_source: str | None,
    audio_storage_provider: str | None,
    audio_object_key: str | None,
) -> None:
    stmt = (
        update(videos)
        .where(videos.c.bvid == bvid)
        .values(
            cid=func.coalesce(cid, videos.c.cid),
            subtitle_source=func.coalesce(transcript_source, videos.c.subtitle_source),
            audio_storage_provider=func.coalesce(
                audio_storage_provider, videos.c.audio_storage_provider
            ),
            audio_object_key=func.coalesce(audio_object_key, videos.c.audio_object_key),
            synced_at=datetime.utcnow(),
        )
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)


async def clear_video_processing_markers(self, bvid: str) -> None:
    stmt = (
        update(videos)
        .where(videos.c.bvid == bvid)
        .values(subtitle_source=None, synced_at=None)
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)


async def reset_video_processing_artifacts(self, bvid: str) -> None:
    async with self.engine.begin() as conn:
        await conn.execute(
            delete(transcripts_tbl).where(transcripts_tbl.c.bvid == bvid)
        )
        await conn.execute(
            delete(video_summaries).where(video_summaries.c.bvid == bvid)
        )
        await conn.execute(delete(video_pipeline).where(video_pipeline.c.bvid == bvid))
        await conn.execute(
            update(videos)
            .where(videos.c.bvid == bvid)
            .values(subtitle_source=None, synced_at=None)
        )
        await conn.execute(
            delete(ingestion_tasks).where(ingestion_tasks.c.bvid == bvid)
        )


async def list_all_video_bvids(self) -> list[str]:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(videos.c.bvid).order_by(videos.c.created_at.asc())
        )
    return list(result.scalars().all())


async def list_all_audio_objects(self) -> list[dict[str, str]]:
    stmt = (
        select(
            videos.c.audio_storage_provider,
            videos.c.audio_object_key,
        )
        .where(
            videos.c.audio_storage_provider.isnot(None),
            videos.c.audio_object_key.isnot(None),
        )
        .distinct()
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    return [dict(row) for row in rows]
