from __future__ import annotations

from bilibrain.graphs.summary.state import SummaryState
from bilibrain.services.common import merge_transcript_segments
from bilibrain.services.summary import (
    SUMMARY_DIRECT_CHARS,
    build_segment_inputs,
    compute_transcript_hash,
    format_window_text,
    pack_summary_windows,
)


async def load_summary_context(state: SummaryState) -> SummaryState:
    runtime = state["runtime"]
    bvid = state["bvid"]
    transcript = runtime.db.get_transcript(bvid)
    if not transcript:
        return {
            "transcript": None,
            "video": runtime.db.get_video(bvid),
        }
    return {
        "transcript": transcript,
        "video": runtime.db.get_video(bvid),
        "transcript_hash": compute_transcript_hash(str(transcript.get("transcript_text") or "")),
        "existing_summary": runtime.db.get_video_summary(bvid),
    }


async def prepare_summary_segments(state: SummaryState) -> SummaryState:
    runtime = state["runtime"]
    transcript = state.get("transcript")
    if not transcript:
        return {"merged_segments": [], "total_chars": 0}

    merged_segments = merge_transcript_segments(
        build_segment_inputs(list(transcript.get("segments") or [])),
        max_gap=runtime.settings.transcript_merge_max_gap,
        max_duration=runtime.settings.transcript_merge_max_duration,
        target_chars=runtime.settings.transcript_chunk_target_chars,
        min_chars=runtime.settings.transcript_chunk_min_chars,
        overlap_chars=runtime.settings.transcript_chunk_overlap_chars,
        max_tokens=runtime.settings.transcript_chunk_max_tokens,
    )
    total_chars = sum(len(str(segment.get("content") or "")) for segment in merged_segments)
    return {
        "merged_segments": merged_segments,
        "total_chars": total_chars,
    }


async def generate_direct_summary(state: SummaryState) -> SummaryState:
    runtime = state["runtime"]
    runtime.qwen.ensure_configured()
    merged_segments = state.get("merged_segments") or []
    video = state.get("video") or {}
    summary_text = await runtime.qwen.summarize_video(
        video_title=str(video.get("title") or state["bvid"]),
        transcript_text=format_window_text(merged_segments),
    )
    return {"summary_text": str(summary_text or "").strip()}


async def generate_window_summaries(state: SummaryState) -> SummaryState:
    runtime = state["runtime"]
    runtime.qwen.ensure_configured()
    merged_segments = state.get("merged_segments") or []
    video = state.get("video") or {}
    window_summaries: list[str] = []
    for window in pack_summary_windows(merged_segments):
        summary = await runtime.qwen.summarize_video_window(
            video_title=str(video.get("title") or state["bvid"]),
            transcript_text=format_window_text(window),
        )
        normalized = str(summary or "").strip()
        if normalized:
            window_summaries.append(normalized)
    return {"window_summaries": window_summaries}


async def reduce_window_summaries(state: SummaryState) -> SummaryState:
    runtime = state["runtime"]
    runtime.qwen.ensure_configured()
    video = state.get("video") or {}
    summary_text = await runtime.qwen.reduce_video_summaries(
        video_title=str(video.get("title") or state["bvid"]),
        window_summaries=state.get("window_summaries") or [],
    )
    return {"summary_text": str(summary_text or "").strip()}


async def save_summary_result(state: SummaryState) -> SummaryState:
    runtime = state["runtime"]
    summary_text = str(state.get("summary_text") or "").strip()
    transcript_hash = str(state.get("transcript_hash") or "").strip()
    if not summary_text or not transcript_hash:
        return {}
    runtime.db.save_video_summary(
        bvid=state["bvid"],
        transcript_hash=transcript_hash,
        summary_text=summary_text,
    )
    return {}


def should_return_cached_summary(state: SummaryState) -> str:
    transcript = state.get("transcript")
    existing_summary = state.get("existing_summary")
    transcript_hash = str(state.get("transcript_hash") or "").strip()
    if not transcript:
        return "no_transcript"
    if (
        existing_summary
        and str(existing_summary.get("transcript_hash") or "") == transcript_hash
        and str(existing_summary.get("summary_text") or "").strip()
    ):
        return "cached"
    return "generate"


def choose_summary_mode(state: SummaryState) -> str:
    merged_segments = state.get("merged_segments") or []
    total_chars = int(state.get("total_chars") or 0)
    if not merged_segments:
        return "empty"
    if total_chars <= SUMMARY_DIRECT_CHARS:
        return "direct"
    return "windowed"
