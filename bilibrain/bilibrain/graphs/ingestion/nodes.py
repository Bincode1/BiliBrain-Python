from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter

from langgraph.runtime import Runtime as GraphRuntime

from bilibrain.graphs.ingestion.helpers import (
    audio_display_path,
    build_segment_inputs,
    duration_limit_message,
    ensure_processable_video,
    hydrate_audio_step_state,
    prepare_audio_input_file,
    require_video,
)
from bilibrain.graphs.ingestion.state import IngestionContext, IngestionState
from bilibrain.services.common import merge_transcript_segments
from bilibrain.services.summary import ensure_video_summary


logger = logging.getLogger(__name__)


async def load_video_context(
    state: IngestionState,
    runtime: GraphRuntime[IngestionContext],
) -> IngestionState:
    app_runtime = runtime.context["runtime"]
    bvid = state["bvid"]
    logger.info("[%s] Loading video context...", bvid)
    video = await require_video(app_runtime, bvid)
    processing_settings = await app_runtime.db.get_processing_settings()
    return {
        "video": video,
        "processing_settings": processing_settings,
        "max_video_minutes": int(processing_settings["max_video_minutes"]),
        "duration_seconds": int(video.get("duration") or 0),
        "current_step": "audio",
    }


async def validate_video_context(
    state: IngestionState,
    runtime: GraphRuntime[IngestionContext],
) -> IngestionState:
    app_runtime = runtime.context["runtime"]
    video = state["video"] or await require_video(app_runtime, state["bvid"])
    ensure_processable_video(video)
    app_runtime.embedder.ensure_configured()

    duration_seconds = int(state.get("duration_seconds") or video.get("duration") or 0)
    max_video_minutes = int(
        state.get("max_video_minutes")
        or (await app_runtime.db.get_processing_settings())["max_video_minutes"]
    )
    if duration_seconds > max_video_minutes * 60:
        raise RuntimeError(duration_limit_message(duration_seconds, max_video_minutes))

    return {
        "video": video,
        "duration_seconds": duration_seconds,
        "max_video_minutes": max_video_minutes,
        "current_step": "audio",
    }


async def ensure_audio_input(
    state: IngestionState,
    runtime: GraphRuntime[IngestionContext],
) -> IngestionState:
    app_runtime = runtime.context["runtime"]
    bvid = state["bvid"]
    video = state["video"] or await require_video(app_runtime, bvid)
    temp_audio_path = Path(state["temp_audio_path"])
    pipeline_state = await app_runtime.db.get_pipeline_state(bvid)
    hydrate_audio_step_state(app_runtime, video, pipeline_state)

    if pipeline_state["audio"]["status"] == "done":
        logger.info("[%s] Audio already exists, skipping download", bvid)
        resolved_path = await prepare_audio_input_file(app_runtime, video, temp_audio_path)
        return {
            "video": video,
            "temp_audio_path": str(resolved_path),
            "current_step": "transcript",
        }

    logger.info("[%s] Downloading audio track...", bvid)
    await app_runtime.db.update_pipeline_step(
        bvid,
        "audio",
        "running",
        path=str(temp_audio_path),
    )
    audio_track = await app_runtime.bili.download_audio_track(bvid, temp_audio_path)
    logger.info("[%s] Audio downloaded, uploading to storage...", bvid)
    audio_object = await app_runtime.audio_storage.upload_audio(temp_audio_path, bvid=bvid)
    logger.info("[%s] Audio stored: %s", bvid, audio_object.object_key)
    await app_runtime.db.mark_video_processed(
        bvid=bvid,
        cid=int(audio_track["cid"]) if audio_track.get("cid") else None,
        transcript_source=None,
        audio_storage_provider=audio_object.provider,
        audio_object_key=audio_object.object_key,
    )
    await app_runtime.db.update_pipeline_step(
        bvid,
        "audio",
        "done",
        provider=audio_object.provider,
        object_key=audio_object.object_key,
        path=audio_display_path(audio_object.provider, audio_object.object_key),
        url=audio_object.url,
    )
    return {
        "video": await require_video(app_runtime, bvid),
        "temp_audio_path": str(temp_audio_path),
        "current_step": "transcript",
    }


async def ensure_transcript_data(
    state: IngestionState,
    runtime: GraphRuntime[IngestionContext],
) -> IngestionState:
    app_runtime = runtime.context["runtime"]
    bvid = state["bvid"]
    transcript = await app_runtime.db.get_transcript(bvid)
    pipeline_state = await app_runtime.db.get_pipeline_state(bvid)

    if pipeline_state["transcript"]["status"] == "done":
        if not transcript:
            await app_runtime.db.update_pipeline_step(
                bvid,
                "transcript",
                "pending",
                source_model=None,
                segment_count=0,
            )
            raise RuntimeError("转写文本不存在，请重试。")
        return {
            "transcript": transcript,
            "current_step": "index",
        }

    if transcript:
        await app_runtime.db.update_pipeline_step(
            bvid,
            "transcript",
            "done",
            source_model=transcript["source_model"],
            segment_count=int(transcript["segment_count"] or 0),
        )
        return {
            "transcript": transcript,
            "current_step": "index",
        }

    app_runtime.asr.ensure_configured()
    logger.info("[%s] Starting ASR transcription...", bvid)
    await app_runtime.db.update_pipeline_step(
        bvid,
        "transcript",
        "running",
        source_model=app_runtime.asr.model_label(),
        segment_count=0,
        substage="chunking",
        substage_label="正在分析静音并切分音频",
    )
    transcript_started = perf_counter()

    async def _handle_progress(event: dict[str, object]) -> None:
        await app_runtime.db.update_pipeline_step(
            bvid,
            "transcript",
            "running",
            source_model=app_runtime.asr.model_label(),
            segment_count=0,
            substage=str(event.get("stage") or "").strip() or None,
            substage_label=str(event.get("message") or "").strip(),
        )

    transcript_payload = await app_runtime.asr.transcribe_audio_file(
        Path(state["temp_audio_path"]),
        on_progress=_handle_progress,
    )
    transcript_elapsed = perf_counter() - transcript_started
    await app_runtime.db.save_transcript(
        bvid=bvid,
        source_model=transcript_payload["model"],
        transcript_text=transcript_payload["text"],
        segments=transcript_payload["segments"],
    )
    await app_runtime.db.update_pipeline_step(
        bvid,
        "transcript",
        "done",
        source_model=transcript_payload["model"],
        segment_count=int(transcript_payload["segment_count"] or 0),
        substage=None,
        substage_label="",
    )
    logger.info(
        "Transcript stage completed for %s: %s segments in %.2fs",
        bvid,
        int(transcript_payload["segment_count"] or 0),
        transcript_elapsed,
    )
    return {
        "transcript": await app_runtime.db.get_transcript(bvid),
        "current_step": "index",
    }


async def build_index_segments(
    state: IngestionState,
    runtime: GraphRuntime[IngestionContext],
) -> IngestionState:
    app_runtime = runtime.context["runtime"]
    bvid = state["bvid"]
    logger.info("[%s] Building index segments...", bvid)
    transcript = state.get("transcript") or await app_runtime.db.get_transcript(bvid)
    if not transcript:
        raise RuntimeError("没有找到可用于建索引的转写文本。")

    await app_runtime.db.update_pipeline_step(
        bvid,
        "index",
        "running",
        substage="chunking",
        substage_label="正在切分文本",
        model=app_runtime.settings.embedding_model,
        count=0,
    )
    merged_segments = merge_transcript_segments(
        build_segment_inputs(transcript["segments"]),
        max_gap=app_runtime.settings.transcript_merge_max_gap,
        max_duration=app_runtime.settings.transcript_merge_max_duration,
        target_chars=app_runtime.settings.transcript_chunk_target_chars,
        min_chars=app_runtime.settings.transcript_chunk_min_chars,
        overlap_chars=app_runtime.settings.transcript_chunk_overlap_chars,
        max_tokens=app_runtime.settings.transcript_chunk_max_tokens,
    )
    if not merged_segments:
        raise RuntimeError("转写文本存在，但没有生成可入库的片段。")

    return {
        "transcript": transcript,
        "merged_segments": merged_segments,
        "current_step": "index",
    }


async def embed_index_segments(
    state: IngestionState,
    runtime: GraphRuntime[IngestionContext],
) -> IngestionState:
    app_runtime = runtime.context["runtime"]
    bvid = state["bvid"]
    merged_segments = state.get("merged_segments") or []
    logger.info("[%s] Embedding %s segments...", bvid, len(merged_segments))
    await app_runtime.db.update_pipeline_step(
        bvid,
        "index",
        "running",
        substage="embedding",
        substage_label="正在生成向量",
        model=app_runtime.settings.embedding_model,
        count=len(merged_segments),
    )
    embeddings = await app_runtime.embedder.embed_texts(
        [segment["content"] for segment in merged_segments]
    )
    chunk_rows: list[dict[str, object]] = []
    for index, (segment, embedding) in enumerate(
        zip(merged_segments, embeddings, strict=False)
    ):
        chunk_rows.append(
            {
                "chunk_id": f"{bvid}-idx-{index}",
                "start_seconds": segment["start_seconds"],
                "end_seconds": segment["end_seconds"],
                "content": segment["content"],
                "embedding": embedding,
            }
        )
    return {
        "chunk_rows": chunk_rows,
        "current_step": "index",
    }


async def upsert_index_chunks(
    state: IngestionState,
    runtime: GraphRuntime[IngestionContext],
) -> IngestionState:
    app_runtime = runtime.context["runtime"]
    bvid = state["bvid"]
    video = state["video"] or await require_video(app_runtime, bvid)
    chunk_rows = state.get("chunk_rows") or []
    logger.info("[%s] Upserting %s chunks to vector store...", bvid, len(chunk_rows))
    await app_runtime.db.update_pipeline_step(
        bvid,
        "index",
        "running",
        substage="vector_upsert",
        substage_label="正在写入向量库",
        model=app_runtime.settings.embedding_model,
        count=len(chunk_rows),
    )
    await app_runtime.vector_store.areplace_video_chunks(
        folder_id=int(video["folder_id"]),
        bvid=bvid,
        video_title=video["title"],
        up_name=video.get("up_name"),
        transcript_source=str(
            (await app_runtime.db.get_transcript(bvid) or {}).get("source_model")
            or app_runtime.asr.model_label()
        ),
        manual_tags=video.get("manual_tags") or [],
        chunks=chunk_rows,
    )
    await app_runtime.db.mark_video_processed(
        bvid=bvid,
        cid=int(video["cid"]) if video.get("cid") else None,
        transcript_source=str(
            (await app_runtime.db.get_transcript(bvid) or {}).get("source_model")
            or app_runtime.asr.model_label()
        ),
        audio_storage_provider=video.get("audio_storage_provider"),
        audio_object_key=video.get("audio_object_key"),
    )
    await app_runtime.db.update_pipeline_step(
        bvid,
        "index",
        "done",
        substage=None,
        substage_label="",
        model=app_runtime.settings.embedding_model,
        count=len(chunk_rows),
    )
    return {
        "video": await require_video(app_runtime, bvid),
        "current_step": "index",
    }


async def maybe_generate_summary(
    state: IngestionState,
    runtime: GraphRuntime[IngestionContext],
) -> IngestionState:
    if state.get("skip_summary"):
        return {}

    app_runtime = runtime.context["runtime"]
    bvid = state["bvid"]
    try:
        logger.info("[%s] Generating summary...", bvid)
        await ensure_video_summary(app_runtime, bvid)
        logger.info("[%s] Summary generated successfully", bvid)
    except Exception as exc:
        logger.warning("[%s] Summary generation failed: %s", bvid, exc)
    return {}
