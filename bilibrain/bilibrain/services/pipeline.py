from __future__ import annotations

import asyncio
from typing import Any

from bilibrain.core.runtime import Runtime
from bilibrain.graphs.ingestion import run_ingestion_graph
from bilibrain.graphs.ingestion.helpers import hydrate_audio_step_state, require_video
from bilibrain.services.ingestion_queue import ACTIVE_TASK_STATUSES, get_active_ingestion_task
from bilibrain.services.common import (
    PIPELINE_STEPS,
    default_pipeline_state,
    pipeline_action_label,
    pipeline_error_message,
    pipeline_overall_status,
    pipeline_step_items,
)


OVERALL_STATUS_LABELS = {
    "pending": "还没有开始处理",
    "partial": "已完成部分步骤",
    "processing": "正在处理中",
    "failed": "处理失败",
    "indexed": "已转写入库",
}
QUEUE_ACTION_LABELS = {
    "queued": "排队中",
    "running": "处理中",
}
RESET_ACTIVE_STATUSES = {"queued", "running"}


def _ensure_reset_runtime_state(runtime: Runtime) -> None:
    if not hasattr(runtime, "reset_tasks") or runtime.reset_tasks is None:
        runtime.reset_tasks = {}
    if not hasattr(runtime, "reset_statuses") or runtime.reset_statuses is None:
        runtime.reset_statuses = {}
    if getattr(runtime, "reset_limiter", None) is None:
        max_concurrency = max(int(getattr(runtime.settings, "reset_max_concurrency", 1)), 1)
        runtime.reset_limiter = asyncio.Semaphore(max_concurrency)


def _active_reset_status(runtime: Runtime, bvid: str) -> str | None:
    _ensure_reset_runtime_state(runtime)
    task = runtime.reset_tasks.get(bvid)
    if task is None or task.done():
        return None
    state = runtime.reset_statuses.get(bvid) or {}
    status = str(state.get("status") or "").strip().lower()
    return status if status in RESET_ACTIVE_STATUSES else "queued"


def _sync_reset_video_processing(runtime: Runtime, bvid: str) -> None:
    require_video(runtime, bvid)
    runtime.db.reset_video_processing_artifacts(bvid)
    runtime.vector_store.delete_video_chunks(bvid)


async def _execute_reset_video_processing(runtime: Runtime, bvid: str) -> None:
    _ensure_reset_runtime_state(runtime)
    try:
        runtime.reset_statuses[bvid] = {"status": "queued", "error": None}
        async with runtime.reset_limiter:
            runtime.reset_statuses[bvid] = {"status": "running", "error": None}
            await asyncio.to_thread(_sync_reset_video_processing, runtime, bvid)
    except asyncio.CancelledError:
        runtime.reset_statuses[bvid] = {"status": "failed", "error": "重置任务已取消。"}
        raise
    except Exception as exc:
        runtime.reset_statuses[bvid] = {"status": "failed", "error": str(exc)}
    else:
        runtime.reset_statuses.pop(bvid, None)
    finally:
        runtime.reset_tasks.pop(bvid, None)


def _consume_reset_task_result(done_task: asyncio.Task[Any]) -> None:
    try:
        done_task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        return


def _sync_reset_all_video_processing(runtime: Runtime) -> dict[str, Any]:
    queued_tasks = runtime.db.list_ingestion_tasks(statuses=["queued"], limit=5000)
    for task in queued_tasks:
        runtime.db.cancel_ingestion_task(int(task["task_id"]))

    bvids = runtime.db.list_all_video_bvids()
    transcript_count = runtime.db.delete_all_transcripts()
    summary_count = runtime.db.delete_all_video_summaries()
    pipeline_count = runtime.db.reset_all_pipeline_states()
    marker_count = runtime.db.clear_all_video_processing_markers()
    deleted_task_count = runtime.db.delete_all_ingestion_tasks()
    runtime.vector_store.reset_collection()

    return {
        "reset": True,
        "video_count": len(bvids),
        "transcript_count": transcript_count,
        "summary_count": summary_count,
        "pipeline_count": pipeline_count,
        "marker_count": marker_count,
        "task_count": deleted_task_count,
    }


def _build_visible_reset_state(runtime: Runtime, video: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    state = default_pipeline_state()
    hydrate_audio_step_state(runtime, video, state)
    return state


def build_status_payload(runtime: Runtime, bvid: str) -> dict[str, Any]:
    video = runtime.db.get_video(bvid)
    transcript = runtime.db.get_transcript(bvid)
    summary = runtime.db.get_video_summary(bvid)
    active_task = get_active_ingestion_task(runtime, bvid)
    state = runtime.db.get_pipeline_state(bvid)
    hydrate_audio_step_state(runtime, video, state)
    overall_status = pipeline_overall_status(state)
    processing_settings = runtime.db.get_processing_settings()
    max_video_minutes = int(processing_settings["max_video_minutes"])
    duration_seconds = int((video or {}).get("duration") or 0)
    over_limit = duration_seconds > max_video_minutes * 60
    task_status = str((active_task or {}).get("status") or "").strip().lower() or None
    is_active = task_status in ACTIVE_TASK_STATUSES
    reset_status = _active_reset_status(runtime, bvid)
    reset_state = getattr(runtime, "reset_statuses", {}).get(bvid) or {}
    reset_active = reset_status in RESET_ACTIVE_STATUSES
    if reset_active:
        state = _build_visible_reset_state(runtime, video)
        transcript = None
        summary = None
    process_active = is_active or (bvid in runtime.video_tasks and not runtime.video_tasks[bvid].done())
    operation = "reset" if reset_active else ("process" if process_active else None)
    error_msg = str(reset_state.get("error") or "").strip() or pipeline_error_message(state)

    return {
        "bvid": bvid,
        "title": video["title"] if video else bvid,
        "duration": duration_seconds,
        "duration_minutes": round(duration_seconds / 60, 1) if duration_seconds else 0,
        "max_video_minutes": max_video_minutes,
        "over_limit": over_limit,
        "overall_status": overall_status,
        "overall_status_label": OVERALL_STATUS_LABELS.get(overall_status, overall_status),
        "action_label": QUEUE_ACTION_LABELS.get(task_status, pipeline_action_label(state)),
        "error_msg": error_msg,
        "chunk_count": int(state["index"].get("count") or 0),
        "running": reset_active or process_active,
        "operation": operation,
        "reset_running": reset_active,
        "reset_status": str(reset_state.get("status") or "").strip().lower() or None,
        "queue_status": task_status,
        "queue_task_id": (active_task or {}).get("task_id"),
        "steps": pipeline_step_items(state),
        "transcript_source": transcript["source_model"] if transcript else state["transcript"].get("source_model"),
        "transcript_segment_count": (
            int(transcript["segment_count"]) if transcript else int(state["transcript"].get("segment_count") or 0)
        ),
        "transcript_updated_at": transcript["updated_at"] if transcript else state["transcript"].get("updated_at"),
        "has_transcript": bool(transcript),
        "has_summary": bool(summary and str(summary.get("summary_text") or "").strip()),
        "summary_updated_at": summary.get("updated_at") if summary else None,
        "manual_tags": (video or {}).get("manual_tags") or [],
        "audio_storage_provider": (video or {}).get("audio_storage_provider"),
        "audio_object_key": (video or {}).get("audio_object_key"),
        "audio_url": runtime.audio_storage.get_audio_url(
            (video or {}).get("audio_storage_provider"),
            (video or {}).get("audio_object_key"),
        ),
    }


def infer_failed_pipeline_step(state: dict[str, dict[str, Any]]) -> str:
    for step in reversed(PIPELINE_STEPS):
        if state[step]["status"] == "running":
            return step
    for step in PIPELINE_STEPS:
        if state[step]["status"] != "done":
            return step
    return PIPELINE_STEPS[0]


async def run_video_pipeline(runtime: Runtime, bvid: str) -> None:
    try:
        await run_ingestion_graph(runtime, bvid)
    except Exception as exc:
        state = runtime.db.get_pipeline_state(bvid)
        current_step = infer_failed_pipeline_step(state)
        step_state = state[current_step]
        runtime.db.update_pipeline_step(
            bvid,
            current_step,
            "failed",
            error=str(exc),
            **{
                key: value
                for key, value in step_state.items()
                if key not in {"status", "error", "updated_at"} and value is not None
            },
        )
        raise
async def start_video_processing(runtime: Runtime, bvid: str) -> dict[str, Any]:
    from bilibrain.services.ingestion_queue import enqueue_video_processing

    return await enqueue_video_processing(runtime, bvid)


async def reset_video_processing(runtime: Runtime, bvid: str) -> dict[str, Any]:
    require_video(runtime, bvid)
    _ensure_reset_runtime_state(runtime)

    active_reset = runtime.reset_tasks.get(bvid)
    if active_reset and not active_reset.done():
        return {**build_status_payload(runtime, bvid), "reset": True, "started": False}

    running_task = runtime.video_tasks.get(bvid)
    if running_task and not running_task.done():
        running_task.cancel()
    runtime.video_tasks.pop(bvid, None)
    runtime.reset_statuses.pop(bvid, None)

    task = asyncio.create_task(_execute_reset_video_processing(runtime, bvid))
    runtime.reset_tasks[bvid] = task
    task.add_done_callback(_consume_reset_task_result)
    await asyncio.sleep(0)
    return {**build_status_payload(runtime, bvid), "reset": True, "started": True}


async def reset_all_video_processing(runtime: Runtime) -> dict[str, Any]:
    _ensure_reset_runtime_state(runtime)
    reset_tasks = list(runtime.reset_tasks.values())
    for task in reset_tasks:
        if not task.done():
            task.cancel()
    if reset_tasks:
        await asyncio.gather(*reset_tasks, return_exceptions=True)
    runtime.reset_tasks.clear()
    runtime.reset_statuses.clear()

    all_tasks = list(runtime.video_tasks.items())
    for _, task in all_tasks:
        if not task.done():
            task.cancel()
    if all_tasks:
        await asyncio.gather(*(task for _, task in all_tasks), return_exceptions=True)
    runtime.video_tasks.clear()
    return await asyncio.to_thread(_sync_reset_all_video_processing, runtime)
