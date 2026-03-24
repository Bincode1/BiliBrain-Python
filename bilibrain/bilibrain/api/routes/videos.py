from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from bilibrain.api.deps import get_runtime
from bilibrain.core.runtime import Runtime
from bilibrain.schemas.requests import TagsRequest
from bilibrain.services.catalog import build_summary_payload, build_transcript_payload, generate_summary_payload
from bilibrain.services.pipeline import (
    build_status_payload,
    require_video,
    reset_all_video_processing,
    reset_video_processing,
    start_video_processing,
)


router = APIRouter()


@router.get("/api/videos/{bvid}/transcript")
async def get_video_transcript(bvid: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return build_transcript_payload(runtime, bvid)


@router.get("/api/videos/{bvid}/summary")
async def get_video_summary(bvid: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return await build_summary_payload(runtime, bvid)


@router.post("/api/videos/{bvid}/summary")
async def generate_video_summary(bvid: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return await generate_summary_payload(runtime, bvid)


@router.get("/api/videos/{bvid}/process/status")
async def get_process_status(bvid: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    require_video(runtime, bvid)
    return build_status_payload(runtime, bvid)


@router.post("/api/videos/{bvid}/process")
async def process_video(bvid: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return await start_video_processing(runtime, bvid)


@router.post("/api/videos/{bvid}/reset")
async def reset_video_processing_route(bvid: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return await reset_video_processing(runtime, bvid)


@router.post("/api/videos/reset-all")
async def reset_all_video_processing_route(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return await reset_all_video_processing(runtime)


@router.post("/api/videos/{bvid}/tags")
async def update_video_tags(
    bvid: str,
    payload: TagsRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    require_video(runtime, bvid)
    tags = runtime.db.set_video_tags(bvid, payload.tags)
    return {"bvid": bvid, "manual_tags": tags}
