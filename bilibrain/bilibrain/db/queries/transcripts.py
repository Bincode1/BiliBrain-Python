from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, update, delete, func, or_, and_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from bilibrain.db.tables import (
    videos,
    transcripts as transcripts_tbl,
    video_summaries,
    video_pipeline,
)
from bilibrain.db.database import _format_datetime
from bilibrain.services.common import (
    default_pipeline_state,
    extract_terms,
    normalize_pipeline_state,
    pipeline_error_message,
    pipeline_overall_status,
)


async def get_transcript(self, bvid: str) -> dict[str, Any] | None:
    async with self.engine.connect() as conn:
        result = await conn.execute(
            select(transcripts_tbl).where(transcripts_tbl.c.bvid == bvid)
        )
        row = result.mappings().first()
    if row is None:
        return None
    d = dict(row)
    try:
        d["segments"] = json.loads(d.get("segments_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["segments"] = []
    d["updated_at"] = _format_datetime(d.get("updated_at"))
    return d


async def save_transcript(
    self,
    *,
    bvid: str,
    source_model: str,
    transcript_text: str,
    segments: list[dict[str, Any]],
) -> None:
    segments_json = json.dumps(segments, ensure_ascii=False)
    stmt = sqlite_insert(transcripts_tbl).values(
        bvid=bvid,
        source_model=source_model,
        transcript_text=transcript_text,
        segments_json=segments_json,
        segment_count=len(segments),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["bvid"],
        set_={
            "source_model": stmt.excluded.source_model,
            "transcript_text": stmt.excluded.transcript_text,
            "segments_json": stmt.excluded.segments_json,
            "segment_count": stmt.excluded.segment_count,
        },
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)


async def delete_transcript(self, bvid: str) -> None:
    async with self.engine.begin() as conn:
        await conn.execute(
            delete(transcripts_tbl).where(transcripts_tbl.c.bvid == bvid)
        )


async def delete_all_transcripts(self) -> int:
    async with self.engine.begin() as conn:
        result = await conn.execute(transcripts_tbl.delete())
    return result.rowcount


async def get_video_summary(self, bvid: str) -> dict[str, Any] | None:
    stmt = (
        select(
            video_summaries.c.bvid,
            video_summaries.c.transcript_hash,
            video_summaries.c.summary_text,
            video_summaries.c.updated_at,
            videos.c.folder_id,
            videos.c.title.label("video_title"),
            videos.c.up_name,
        )
        .select_from(
            video_summaries.outerjoin(videos, videos.c.bvid == video_summaries.c.bvid)
        )
        .where(video_summaries.c.bvid == bvid)
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        row = result.mappings().first()
    if row is None:
        return None
    d = dict(row)
    d["updated_at"] = _format_datetime(d.get("updated_at"))
    return d


async def list_video_summaries(
    self, folder_id: int | None = None
) -> list[dict[str, Any]]:
    stmt = (
        select(
            video_summaries.c.bvid,
            video_summaries.c.transcript_hash,
            video_summaries.c.summary_text,
            video_summaries.c.updated_at,
            videos.c.folder_id,
            videos.c.title.label("video_title"),
            videos.c.up_name,
        )
        .select_from(
            video_summaries.outerjoin(videos, videos.c.bvid == video_summaries.c.bvid)
        )
        .order_by(func.coalesce(videos.c.published_at, videos.c.created_at).desc())
    )
    if folder_id is not None:
        stmt = stmt.where(videos.c.folder_id == folder_id)
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["updated_at"] = _format_datetime(d.get("updated_at"))
        items.append(d)
    return items


async def search_video_summaries(
    self,
    query_text: str,
    *,
    folder_id: int | None = None,
    bvid: str | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    terms = extract_terms(query_text)
    if not terms:
        return []

    or_conditions: list = []
    for term in terms:
        like_pattern = f"%{term}%"
        or_conditions.append(
            or_(
                videos.c.title.like(like_pattern),
                videos.c.up_name.like(like_pattern),
                video_summaries.c.summary_text.like(like_pattern),
            )
        )

    conditions: list = [and_(*or_conditions)]
    if folder_id is not None:
        conditions.append(videos.c.folder_id == folder_id)
    if bvid is not None:
        conditions.append(video_summaries.c.bvid == bvid)

    stmt = (
        select(
            video_summaries.c.bvid,
            video_summaries.c.transcript_hash,
            video_summaries.c.summary_text,
            video_summaries.c.updated_at,
            videos.c.folder_id,
            videos.c.title.label("video_title"),
            videos.c.up_name,
        )
        .select_from(
            video_summaries.outerjoin(videos, videos.c.bvid == video_summaries.c.bvid)
        )
        .where(and_(*conditions))
        .order_by(func.coalesce(videos.c.published_at, videos.c.created_at).desc())
        .limit(50)
    )

    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()

    hits: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["updated_at"] = _format_datetime(d.get("updated_at"))
        d["content"] = str(d.get("summary_text") or "")
        d["score"] = 0.0
        hits.append(d)

    if not hits:
        return []

    rescored: list[dict[str, Any]] = []
    for hit in hits:
        combined_text = f"{hit.get('video_title', '')} {hit.get('up_name', '')} {hit.get('content', '')}"
        hit_terms = extract_terms(combined_text)
        overlap = len(terms & hit_terms)
        keyword_score = overlap / max(len(terms), 1)
        if keyword_score <= 0:
            continue
        rescored.append({**hit, "score": keyword_score})

    rescored.sort(key=lambda item: item["score"], reverse=True)
    return rescored[:limit]


async def save_video_summary(
    self,
    *,
    bvid: str,
    transcript_hash: str,
    summary_text: str,
) -> None:
    stmt = sqlite_insert(video_summaries).values(
        bvid=bvid,
        transcript_hash=transcript_hash,
        summary_text=summary_text,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["bvid"],
        set_={
            "transcript_hash": stmt.excluded.transcript_hash,
            "summary_text": stmt.excluded.summary_text,
        },
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)


async def delete_video_summary(self, bvid: str) -> None:
    async with self.engine.begin() as conn:
        await conn.execute(
            delete(video_summaries).where(video_summaries.c.bvid == bvid)
        )


async def delete_all_video_summaries(self) -> int:
    async with self.engine.begin() as conn:
        result = await conn.execute(video_summaries.delete())
    return result.rowcount


async def get_pipeline_state(self, bvid: str) -> dict[str, dict[str, Any]]:
    stmt = (
        select(
            videos.c.audio_storage_provider,
            videos.c.audio_object_key,
            videos.c.audio_uploaded_at,
            videos.c.synced_at,
            video_pipeline.c.state_json,
            transcripts_tbl.c.source_model.label("transcript_source"),
            transcripts_tbl.c.segment_count,
            transcripts_tbl.c.updated_at.label("transcript_updated_at"),
        )
        .select_from(
            videos.outerjoin(
                video_pipeline, video_pipeline.c.bvid == videos.c.bvid
            ).outerjoin(transcripts_tbl, transcripts_tbl.c.bvid == videos.c.bvid)
        )
        .where(videos.c.bvid == bvid)
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        row = result.mappings().first()
    if row is None:
        return default_pipeline_state()
    d = dict(row)
    return self._hydrate_pipeline_state(
        bvid=bvid,
        raw_state_json=d.get("state_json"),
        transcript_source=d.get("transcript_source"),
        transcript_segment_count=d.get("segment_count"),
        transcript_updated_at=d.get("transcript_updated_at"),
        audio_storage_provider=d.get("audio_storage_provider"),
        audio_object_key=d.get("audio_object_key"),
        audio_uploaded_at=d.get("audio_uploaded_at"),
        synced_at=d.get("synced_at"),
    )


async def get_pipeline_overall_statuses(self, bvids: list[str]) -> dict[str, str]:
    if not bvids:
        return {}
    stmt = select(
        video_pipeline.c.bvid,
        video_pipeline.c.state_json,
        video_pipeline.c.overall_status,
    ).where(video_pipeline.c.bvid.in_(bvids))
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    statuses: dict[str, str] = {}
    for row in rows:
        d = dict(row)
        row_bvid = str(d["bvid"])
        state_json = d.get("state_json")
        if state_json:
            state = normalize_pipeline_state(json.loads(state_json))
            statuses[row_bvid] = pipeline_overall_status(state)
        else:
            statuses[row_bvid] = str(d.get("overall_status") or "pending")
    return statuses


async def save_pipeline_state(
    self,
    bvid: str,
    state: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    normalized = normalize_pipeline_state(state)
    overall = pipeline_overall_status(normalized)
    index_count = int(normalized.get("index", {}).get("count") or 0)
    stmt = sqlite_insert(video_pipeline).values(
        bvid=bvid,
        overall_status=overall,
        index_chunk_count=index_count,
        state_json=json.dumps(normalized, ensure_ascii=False),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["bvid"],
        set_={
            "overall_status": stmt.excluded.overall_status,
            "index_chunk_count": stmt.excluded.index_chunk_count,
            "state_json": stmt.excluded.state_json,
        },
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)
    return normalized


async def update_pipeline_step(
    self,
    bvid: str,
    step: str,
    status: str,
    *,
    error: str | None = None,
    **extra: Any,
) -> dict[str, dict[str, Any]]:
    state = await self.get_pipeline_state(bvid)
    if step in state:
        state[step]["status"] = status
        if error is not None:
            state[step]["error"] = error
        for key, value in extra.items():
            state[step][key] = value
    return await self.save_pipeline_state(bvid, state)


async def reset_pipeline_state(self, bvid: str) -> None:
    async with self.engine.begin() as conn:
        await conn.execute(delete(video_pipeline).where(video_pipeline.c.bvid == bvid))


async def reset_all_pipeline_states(self) -> int:
    async with self.engine.begin() as conn:
        result = await conn.execute(video_pipeline.delete())
    return result.rowcount


async def clear_all_video_processing_markers(self) -> int:
    async with self.engine.begin() as conn:
        result = await conn.execute(
            update(videos).values(subtitle_source=None, synced_at=None)
        )
    return result.rowcount
