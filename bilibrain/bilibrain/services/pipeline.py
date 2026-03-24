from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from bilibrain.core.runtime import Runtime
from bilibrain.services.common import (
    merge_subtitle_segments,
    pipeline_action_label,
    pipeline_error_message,
    pipeline_overall_status,
    pipeline_step_items,
)
from bilibrain.services.summary import ensure_video_summary


OVERALL_STATUS_LABELS = {
    "pending": "还没有开始处理",
    "partial": "已完成部分步骤",
    "processing": "正在处理中",
    "failed": "处理失败",
    "indexed": "已转写入库",
}
def audio_display_path(provider: str | None, object_key: str | None) -> str | None:
    if not provider or not object_key:
        return None
    if provider == "local":
        return f"local://{object_key}"
    return f"{provider}://{object_key}"


def duration_limit_message(duration_seconds: int, max_minutes: int) -> str:
    actual_minutes = max(duration_seconds / 60, 0)
    return f"视频时长 {actual_minutes:.1f} 分钟，超过当前 {max_minutes} 分钟限制。"


def require_video(runtime: Runtime, bvid: str) -> dict[str, Any]:
    video = runtime.db.get_video(bvid)
    if not video:
        raise RuntimeError("找不到这个视频，请先读取收藏夹内容。")
    return video


def ensure_processable_video(video: dict[str, Any]) -> None:
    if bool(video.get("is_invalid")):
        raise RuntimeError("失效视频无法处理。")


def hydrate_audio_step_state(runtime: Runtime, video: dict[str, Any] | None, state: dict[str, dict[str, Any]]) -> None:
    if state["audio"]["status"] != "pending":
        return
    provider = (video or {}).get("audio_storage_provider")
    object_key = (video or {}).get("audio_object_key")
    if provider and object_key:
        state["audio"].update(
            {
                "status": "done",
                "provider": provider,
                "object_key": object_key,
                "path": audio_display_path(provider, object_key),
                "url": runtime.audio_storage.get_audio_url(provider, object_key),
            }
        )


async def prepare_audio_input_file(runtime: Runtime, video: dict[str, Any], target_path: Path) -> Path:
    provider = video.get("audio_storage_provider")
    object_key = video.get("audio_object_key")
    if provider and object_key:
        return await runtime.audio_storage.download_audio(str(provider), str(object_key), target_path)

    raise RuntimeError("音频对象不存在，请重试。")


async def remove_stored_audio(runtime: Runtime, video: dict[str, Any] | None) -> bool:
    if not video:
        return False

    removed = False
    provider = video.get("audio_storage_provider")
    object_key = video.get("audio_object_key")
    if provider and object_key:
        await runtime.audio_storage.delete_audio(str(provider), str(object_key))
        removed = True
    return removed


def build_status_payload(runtime: Runtime, bvid: str) -> dict[str, Any]:
    video = runtime.db.get_video(bvid)
    transcript = runtime.db.get_transcript(bvid)
    summary = runtime.db.get_video_summary(bvid)
    state = runtime.db.get_pipeline_state(bvid)
    hydrate_audio_step_state(runtime, video, state)
    overall_status = pipeline_overall_status(state)
    processing_settings = runtime.db.get_processing_settings()
    max_video_minutes = int(processing_settings["max_video_minutes"])
    duration_seconds = int((video or {}).get("duration") or 0)
    over_limit = duration_seconds > max_video_minutes * 60

    return {
        "bvid": bvid,
        "title": video["title"] if video else bvid,
        "duration": duration_seconds,
        "duration_minutes": round(duration_seconds / 60, 1) if duration_seconds else 0,
        "max_video_minutes": max_video_minutes,
        "over_limit": over_limit,
        "overall_status": overall_status,
        "overall_status_label": OVERALL_STATUS_LABELS.get(overall_status, overall_status),
        "action_label": pipeline_action_label(state),
        "error_msg": pipeline_error_message(state),
        "chunk_count": int(state["index"].get("count") or 0),
        "running": bvid in runtime.video_tasks and not runtime.video_tasks[bvid].done(),
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


def build_segment_inputs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for segment in segments:
        start_seconds = float(segment.get("start_seconds", segment.get("from", 0)) or 0)
        end_seconds = float(segment.get("end_seconds", segment.get("to", start_seconds)) or start_seconds)
        content = str(segment.get("content") or "").strip()
        if not content:
            continue
        items.append(
            {
                "from": start_seconds,
                "to": end_seconds,
                "content": content,
            }
        )
    return items


async def run_video_pipeline(runtime: Runtime, bvid: str) -> None:
    runtime.embedder.ensure_configured()
    video = require_video(runtime, bvid)
    ensure_processable_video(video)

    max_video_minutes = int(runtime.db.get_processing_settings()["max_video_minutes"])
    duration_seconds = int(video.get("duration") or 0)
    current_step = "audio"
    try:
        if duration_seconds > max_video_minutes * 60:
            raise RuntimeError(duration_limit_message(duration_seconds, max_video_minutes))

        with tempfile.TemporaryDirectory(prefix="bilibrain-audio-") as temp_dir:
            temp_audio_path = Path(temp_dir) / f"{bvid}.m4a"
            state = runtime.db.get_pipeline_state(bvid)
            hydrate_audio_step_state(runtime, video, state)
            audio_track = None

            if state["audio"]["status"] != "done":
                runtime.db.update_pipeline_step(
                    bvid,
                    "audio",
                    "running",
                    path=str(temp_audio_path),
                )
                audio_track = await runtime.bili.download_audio_track(bvid, temp_audio_path)
                audio_object = await runtime.audio_storage.upload_audio(temp_audio_path, bvid=bvid)
                runtime.db.mark_video_processed(
                    bvid=bvid,
                    cid=int(audio_track["cid"]) if audio_track and audio_track.get("cid") else None,
                    subtitle_source=None,
                    audio_storage_provider=audio_object.provider,
                    audio_object_key=audio_object.object_key,
                )
                runtime.db.update_pipeline_step(
                    bvid,
                    "audio",
                    "done",
                    provider=audio_object.provider,
                    object_key=audio_object.object_key,
                    path=audio_display_path(audio_object.provider, audio_object.object_key),
                    url=audio_object.url,
                )
                video = require_video(runtime, bvid)
            else:
                temp_audio_path = await prepare_audio_input_file(runtime, video, temp_audio_path)

            current_step = "transcript"
            transcript = runtime.db.get_transcript(bvid)
            if state["transcript"]["status"] != "done":
                if transcript:
                    runtime.db.update_pipeline_step(
                        bvid,
                        "transcript",
                        "done",
                        source_model=transcript["source_model"],
                        segment_count=int(transcript["segment_count"] or 0),
                    )
                else:
                    runtime.db.update_pipeline_step(
                        bvid,
                        "transcript",
                        "running",
                        source_model=runtime.settings.asr_model,
                        segment_count=0,
                    )
                    transcript_payload = await runtime.asr.transcribe_audio_file(temp_audio_path)
                    runtime.db.save_transcript(
                        bvid=bvid,
                        source_model=transcript_payload["model"],
                        transcript_text=transcript_payload["text"],
                        segments=transcript_payload["segments"],
                    )
                    runtime.db.update_pipeline_step(
                        bvid,
                        "transcript",
                        "done",
                        source_model=transcript_payload["model"],
                        segment_count=int(transcript_payload["segment_count"] or 0),
                    )
            elif not transcript:
                runtime.db.update_pipeline_step(
                    bvid,
                    "transcript",
                    "pending",
                    source_model=None,
                    segment_count=0,
                )
                raise RuntimeError("转写文本不存在，请重试。")

            current_step = "index"
            state = runtime.db.get_pipeline_state(bvid)
            transcript = runtime.db.get_transcript(bvid)
            if state["index"]["status"] != "done":
                if not transcript:
                    raise RuntimeError("没有找到可用于建索引的转写文本。")

                segment_inputs = build_segment_inputs(transcript["segments"])
                runtime.db.update_pipeline_step(
                    bvid,
                    "index",
                    "running",
                    substage="chunking",
                    substage_label="正在切分文本",
                    model=runtime.settings.embedding_model,
                    count=0,
                )
                merged_segments = merge_subtitle_segments(
                    segment_inputs,
                    max_gap=runtime.settings.subtitle_merge_max_gap,
                    max_duration=runtime.settings.subtitle_merge_max_duration,
                    target_chars=runtime.settings.subtitle_chunk_target_chars,
                    min_chars=runtime.settings.subtitle_chunk_min_chars,
                    overlap_chars=runtime.settings.subtitle_chunk_overlap_chars,
                    max_tokens=runtime.settings.subtitle_chunk_max_tokens,
                )
                if not merged_segments:
                    raise RuntimeError("转写文本存在，但没有生成可入库的片段。")

                runtime.db.update_pipeline_step(
                    bvid,
                    "index",
                    "running",
                    substage="embedding",
                    substage_label="正在生成向量",
                    model=runtime.settings.embedding_model,
                    count=len(merged_segments),
                )
                embeddings = await runtime.embedder.embed_texts([segment["content"] for segment in merged_segments])
                chunk_rows = []
                for index, (segment, embedding) in enumerate(zip(merged_segments, embeddings, strict=False)):
                    chunk_rows.append(
                        {
                            "chunk_id": f"{bvid}-idx-{index}",
                            "start_seconds": segment["start_seconds"],
                            "end_seconds": segment["end_seconds"],
                            "content": segment["content"],
                            "embedding": embedding,
                        }
                    )

                runtime.db.update_pipeline_step(
                    bvid,
                    "index",
                    "running",
                    substage="milvus_upsert",
                    substage_label="正在写入 Milvus",
                    model=runtime.settings.embedding_model,
                    count=len(chunk_rows),
                )
                runtime.vector_store.replace_video_chunks(
                    folder_id=int(video["folder_id"]),
                    bvid=bvid,
                    video_title=video["title"],
                    up_name=video.get("up_name"),
                    subtitle_source="asr-manual",
                    manual_tags=video.get("manual_tags") or [],
                    chunks=chunk_rows,
                )
                runtime.db.mark_video_processed(
                    bvid=bvid,
                    cid=int(video["cid"]) if video.get("cid") else None,
                    subtitle_source="asr-manual",
                    audio_storage_provider=video.get("audio_storage_provider"),
                    audio_object_key=video.get("audio_object_key"),
                )
                runtime.db.update_pipeline_step(
                    bvid,
                    "index",
                    "done",
                    substage=None,
                    substage_label="",
                    model=runtime.settings.embedding_model,
                    count=len(chunk_rows),
                )
                try:
                    await ensure_video_summary(runtime, bvid)
                except Exception:
                    pass
    except Exception as exc:
        state = runtime.db.get_pipeline_state(bvid)
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


def track_video_task(runtime: Runtime, bvid: str, task: asyncio.Task[Any]) -> None:
    runtime.video_tasks[bvid] = task

    def cleanup(done_task: asyncio.Task[Any]) -> None:
        runtime.video_tasks.pop(bvid, None)
        try:
            done_task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            return

    task.add_done_callback(cleanup)


async def start_video_processing(runtime: Runtime, bvid: str) -> dict[str, Any]:
    video = require_video(runtime, bvid)
    ensure_processable_video(video)

    running_task = runtime.video_tasks.get(bvid)
    if running_task and not running_task.done():
        return {**build_status_payload(runtime, bvid), "started": False}

    status_payload = build_status_payload(runtime, bvid)
    if status_payload["overall_status"] == "indexed":
        return {**status_payload, "started": False}

    task = asyncio.create_task(run_video_pipeline(runtime, bvid))
    track_video_task(runtime, bvid, task)
    return {**build_status_payload(runtime, bvid), "started": True}


async def reset_video_processing(runtime: Runtime, bvid: str) -> dict[str, Any]:
    video = require_video(runtime, bvid)

    running_task = runtime.video_tasks.get(bvid)
    if running_task and not running_task.done():
        running_task.cancel()
        await asyncio.gather(running_task, return_exceptions=True)

    await remove_stored_audio(runtime, video)
    runtime.db.delete_transcript(bvid)
    runtime.db.delete_video_summary(bvid)
    runtime.db.reset_pipeline_state(bvid)
    runtime.db.clear_video_processing_markers(bvid)
    runtime.vector_store.delete_video_chunks(bvid)
    return {**build_status_payload(runtime, bvid), "reset": True}


async def reset_all_video_processing(runtime: Runtime) -> dict[str, Any]:
    all_tasks = list(runtime.video_tasks.items())
    for _, task in all_tasks:
        if not task.done():
            task.cancel()
    if all_tasks:
        await asyncio.gather(*(task for _, task in all_tasks), return_exceptions=True)
    runtime.video_tasks.clear()

    audio_objects = runtime.db.list_all_audio_objects()
    removed_audio_files = 0
    for item in audio_objects:
        await runtime.audio_storage.delete_audio(item["provider"], item["object_key"])
        removed_audio_files += 1

    if runtime.settings.audio_cache_dir.exists():
        for audio_path in runtime.settings.audio_cache_dir.glob("*.m4a"):
            if audio_path.is_file():
                audio_path.unlink()

    bvids = runtime.db.list_all_video_bvids()
    transcript_count = runtime.db.delete_all_transcripts()
    summary_count = runtime.db.delete_all_video_summaries()
    pipeline_count = runtime.db.reset_all_pipeline_states()
    marker_count = runtime.db.clear_all_video_processing_markers()
    runtime.vector_store.reset_collection()

    return {
        "reset": True,
        "video_count": len(bvids),
        "transcript_count": transcript_count,
        "summary_count": summary_count,
        "pipeline_count": pipeline_count,
        "marker_count": marker_count,
        "audio_file_count": removed_audio_files,
    }
