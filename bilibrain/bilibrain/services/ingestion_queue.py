from __future__ import annotations

from typing import Any

from bilibrain.core.runtime import Runtime
from bilibrain.graphs.ingestion.helpers import require_video


ACTIVE_TASK_STATUSES = {"queued", "running"}


async def get_active_ingestion_task(
    runtime: Runtime, bvid: str
) -> dict[str, Any] | None:
    return await runtime.db.get_active_ingestion_task_for_bvid(bvid)


async def enqueue_video_processing(runtime: Runtime, bvid: str) -> dict[str, Any]:
    from bilibrain.services.pipeline import build_status_payload

    async with runtime.ingestion_enqueue_lock:
        video = await require_video(runtime, bvid)
        if bool(video.get("is_invalid")):
            raise RuntimeError("失效视频无法处理。")

        existing_task = await get_active_ingestion_task(runtime, bvid)
        if existing_task:
            return {
                **await build_status_payload(runtime, bvid),
                "started": False,
                "task_id": existing_task["task_id"],
            }

        status_payload = await build_status_payload(runtime, bvid)
        if status_payload["overall_status"] == "indexed" or status_payload["running"]:
            return {**status_payload, "started": False}

        task = await runtime.db.create_ingestion_task(bvid=bvid)
        return {
            **await build_status_payload(runtime, bvid),
            "started": True,
            "task_id": task["task_id"],
        }


async def list_ingestion_tasks_payload(
    runtime: Runtime,
    *,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    statuses = [status] if status else None
    tasks = await runtime.db.list_ingestion_tasks(statuses=statuses, limit=limit)
    return {"tasks": tasks}
