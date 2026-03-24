from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from bilibrain.api.deps import get_runtime
from bilibrain.core.runtime import Runtime
from bilibrain.schemas.requests import SyncRequest
from bilibrain.services.catalog import build_folder_videos_payload, build_folders_payload, sync_folder_metadata


router = APIRouter()


@router.get("/api/folders")
async def list_folders(uid: int | None = None, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return await build_folders_payload(runtime, uid)


@router.get("/api/overview")
async def overview() -> dict[str, Any]:
    return {"topics": []}


@router.get("/api/folders/{folder_id}/videos")
async def list_folder_videos(folder_id: int, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return await build_folder_videos_payload(runtime, folder_id)


@router.post("/api/sync")
async def sync_folder(payload: SyncRequest, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return await sync_folder_metadata(runtime, payload.folder_id)
