from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from bilibrain.api.deps import get_runtime
from bilibrain.core.runtime import Runtime
from bilibrain.schemas.requests import SettingsRequest


router = APIRouter()


@router.get("/", include_in_schema=False)
async def index(runtime: Runtime = Depends(get_runtime)) -> FileResponse:
    return FileResponse(runtime.settings.index_file)


@router.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/settings")
async def get_settings_payload(
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, int]:
    return await runtime.db.get_processing_settings()


@router.post("/api/settings")
async def update_settings(
    payload: SettingsRequest, runtime: Runtime = Depends(get_runtime)
) -> dict[str, int]:
    return await runtime.db.save_processing_settings(
        max_video_minutes=payload.max_video_minutes
    )
