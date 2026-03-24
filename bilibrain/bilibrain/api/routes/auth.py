from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from bilibrain.api.deps import get_runtime
from bilibrain.core.runtime import Runtime


router = APIRouter()


@router.get("/api/auth/session")
async def auth_session(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return await runtime.bili.get_session()


@router.post("/api/auth/qr/start")
async def auth_qr_start(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return await runtime.bili.start_qr_login()


@router.get("/api/auth/qr/poll")
async def auth_qr_poll(qrcode_key: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return await runtime.bili.poll_qr_login(qrcode_key)
