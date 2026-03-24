from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Awaitable, Callable

from bilibrain.core.runtime import Runtime
from bilibrain.services.summary import ensure_video_summary


VIDEO_FIELDS = [
    "bvid",
    "title",
    "up_name",
    "duration",
    "published_at",
    "cover_url",
    "cid",
    "manual_tags",
    "subtitle_source",
    "transcript_source",
    "transcript_segment_count",
    "transcript_updated_at",
    "sync_status",
    "chunk_count",
    "pipeline",
    "synced_at",
    "error_msg",
]

FOLDER_LIST_CACHE_PREFIX = "cache:folders"
FOLDER_VIDEOS_CACHE_PREFIX = "cache:folder-videos"


def _utcnow() -> datetime:
    return datetime.now()


def _cache_is_fresh(updated_at: datetime | None, ttl_seconds: int) -> bool:
    if not updated_at:
        return False
    return (_utcnow() - updated_at).total_seconds() < max(ttl_seconds, 1)


def _schedule_cache_task(
    runtime: Runtime,
    task_key: str,
    operation_factory: Callable[[], Awaitable[Any]],
) -> None:
    existing = runtime.cache_tasks.get(task_key)
    if existing and not existing.done():
        return

    async def runner() -> None:
        try:
            await operation_factory()
        except Exception:
            return

    task = asyncio.create_task(runner())
    runtime.cache_tasks[task_key] = task

    def cleanup(completed: asyncio.Task[Any]) -> None:
        current = runtime.cache_tasks.get(task_key)
        if current is completed:
            runtime.cache_tasks.pop(task_key, None)

    task.add_done_callback(cleanup)


def folder_list_cache_key(uid: int) -> str:
    return f"{FOLDER_LIST_CACHE_PREFIX}:{uid}"


def folder_videos_cache_key(folder_id: int) -> str:
    return f"{FOLDER_VIDEOS_CACHE_PREFIX}:{folder_id}"


async def refresh_folder_videos(runtime: Runtime, folder_id: int) -> list[dict[str, Any]]:
    live_videos = await runtime.bili.list_folder_videos(folder_id)
    for video in live_videos:
        video["folder_id"] = folder_id
        runtime.db.upsert_video(video)
    runtime.db.save_state(folder_videos_cache_key(folder_id), {"folder_id": int(folder_id)})
    return live_videos


async def refresh_folders(runtime: Runtime, uid: int) -> list[dict[str, Any]]:
    folders = await runtime.bili.list_folders(uid)
    runtime.db.save_state(folder_list_cache_key(uid), {"uid": int(uid)})
    return folders


async def build_folders_payload(runtime: Runtime, uid: int | None = None) -> dict[str, Any]:
    target_uid = int(uid or 0)
    if not target_uid:
        session = await runtime.bili.get_session()
        if not session.get("logged_in"):
            raise RuntimeError("请先扫码登录 Bilibili。")
        target_uid = int(session.get("uid") or 0)
    if not target_uid:
        raise RuntimeError("当前登录状态缺少 UID，无法读取收藏夹。")

    cache_key = folder_list_cache_key(target_uid)
    cached_folders = runtime.db.get_folders_by_uid(target_uid)
    cached_at = runtime.db.get_state_updated_at(cache_key)
    has_cache = bool(cached_folders) or cached_at is not None

    if not has_cache:
        folders = await refresh_folders(runtime, target_uid)
        return {"folders": folders, "stats": runtime.db.get_counts(), "cached": False, "stale": False}

    is_fresh = _cache_is_fresh(cached_at, runtime.settings.folder_list_cache_ttl_seconds)
    if not is_fresh:
        _schedule_cache_task(runtime, cache_key, lambda: refresh_folders(runtime, target_uid))

    return {
        "folders": cached_folders,
        "stats": runtime.db.get_counts(),
        "cached": True,
        "stale": not is_fresh,
    }


async def build_folder_videos_payload(runtime: Runtime, folder_id: int) -> dict[str, Any]:
    folder = runtime.db.get_folder(folder_id)
    if not folder:
        raise RuntimeError("找不到这个收藏夹，请先读取收藏夹列表。")

    cache_key = folder_videos_cache_key(folder_id)
    videos = runtime.db.get_video_records(folder_id)
    cached_at = runtime.db.get_state_updated_at(cache_key)
    has_cache = bool(videos) or cached_at is not None

    if not has_cache:
        await refresh_folder_videos(runtime, folder_id)
        videos = runtime.db.get_video_records(folder_id)
        cached_at = runtime.db.get_state_updated_at(cache_key)
    else:
        is_fresh = _cache_is_fresh(cached_at, runtime.settings.folder_videos_cache_ttl_seconds)
        if not is_fresh:
            _schedule_cache_task(runtime, cache_key, lambda: refresh_folder_videos(runtime, folder_id))

    is_fresh = _cache_is_fresh(cached_at, runtime.settings.folder_videos_cache_ttl_seconds)
    return {
        "folder": {
            "folder_id": folder["folder_id"],
            "title": folder["title"],
            "media_count": folder["media_count"],
        },
        "fields": VIDEO_FIELDS,
        "videos": videos,
        "cached": has_cache,
        "stale": has_cache and not is_fresh,
    }


def build_transcript_payload(runtime: Runtime, bvid: str) -> dict[str, Any]:
    video = runtime.db.get_video(bvid)
    transcript = runtime.db.get_transcript(bvid)
    if not transcript:
        raise RuntimeError("这个视频还没有转写，请先开始处理。")
    return {
        "bvid": bvid,
        "title": video["title"] if video else bvid,
        "transcript_source": transcript["source_model"],
        "segment_count": transcript["segment_count"],
        "segments": transcript["segments"],
        "text": transcript["transcript_text"],
        "updated_at": transcript["updated_at"],
        "cached": True,
    }


async def build_summary_payload(runtime: Runtime, bvid: str) -> dict[str, Any]:
    video = runtime.db.get_video(bvid)
    transcript = runtime.db.get_transcript(bvid)
    if not transcript:
        raise RuntimeError("这个视频还没有转写，请先开始处理。")

    summary = runtime.db.get_video_summary(bvid)
    if not summary or not str(summary.get("summary_text") or "").strip():
        raise RuntimeError("这个视频还没有摘要，请先点击生成摘要。")

    return {
        "bvid": bvid,
        "title": video["title"] if video else bvid,
        "text": summary["summary_text"],
        "updated_at": summary.get("updated_at"),
        "cached": True,
    }


async def generate_summary_payload(runtime: Runtime, bvid: str) -> dict[str, Any]:
    video = runtime.db.get_video(bvid)
    transcript = runtime.db.get_transcript(bvid)
    if not transcript:
        raise RuntimeError("这个视频还没有转写，请先开始处理。")

    summary = await ensure_video_summary(runtime, bvid)
    if not summary or not str(summary.get("summary_text") or "").strip():
        raise RuntimeError("摘要生成失败，请稍后重试。")

    return {
        "bvid": bvid,
        "title": video["title"] if video else bvid,
        "text": summary["summary_text"],
        "updated_at": summary.get("updated_at"),
        "cached": False,
    }


async def sync_folder_metadata(runtime: Runtime, folder_id: int) -> dict[str, Any]:
    folder = runtime.db.get_folder(folder_id)
    videos = await runtime.bili.list_folder_videos(folder_id)
    runtime.db.save_state(folder_videos_cache_key(folder_id), {"folder_id": int(folder_id)})
    logs = [f"发现 {len(videos)} 个视频。"]
    new_videos = 0
    updated_videos = 0
    failed_videos = 0
    errors: list[dict[str, str]] = []

    for video in videos:
        bvid = video["bvid"]
        video["folder_id"] = folder_id
        try:
            if runtime.db.get_video(bvid):
                updated_videos += 1
            else:
                new_videos += 1
            runtime.db.upsert_video(video)
        except Exception as exc:
            failed_videos += 1
            errors.append(
                {
                    "bvid": bvid,
                    "title": video["title"],
                    "error": str(exc),
                }
            )

    counts = runtime.db.get_counts()
    logs.append(f"新增 {new_videos} 个视频，更新 {updated_videos} 个视频元数据。")
    logs.append("同步只刷新元数据，真正花钱的步骤是右侧手动开始处理。")
    if failed_videos:
        logs.append(f"失败 {failed_videos} 个视频，请查看 errors。")

    return {
        "folder": folder["title"] if folder else str(folder_id),
        "failed_videos": failed_videos,
        "logs": logs,
        "errors": errors,
        "stats": counts,
    }
