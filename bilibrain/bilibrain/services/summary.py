from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from bilibrain.services.common import build_jump_url, merge_subtitle_segments, seconds_to_timestamp

if TYPE_CHECKING:
    from bilibrain.core.runtime import Runtime


SUMMARY_DIRECT_CHARS = 5000
SUMMARY_WINDOW_CHARS = 4500
SUMMARY_GROUP_MAX_DOCS = 8
SUMMARY_GROUP_MAX_CHARS = 12000
SUMMARY_AUTOGEN_FOLDER_LIMIT = 6

SUMMARY_KEYWORDS = (
    "总结",
    "概括",
    "归纳",
    "梳理",
    "主要内容",
    "核心内容",
    "核心观点",
    "讲了什么",
    "说了什么",
    "主要讲",
)
FOLDER_SCOPE_KEYWORDS = (
    "收藏夹",
    "这些视频",
    "文件夹",
    "这一组",
    "这组视频",
    "这一批视频",
)
VIDEO_SCOPE_KEYWORDS = (
    "这个视频",
    "这条视频",
    "这期视频",
    "本视频",
    "当前视频",
    "这期",
)


def normalize_scope_mode(scope_mode: str | None) -> str | None:
    normalized = str(scope_mode or "").strip().lower()
    if normalized in {"video", "folder", "global"}:
        return normalized
    return None


def resolve_query_scope(
    *,
    folder_id: int | None = None,
    bvid: str | None = None,
    scope_mode: str | None = None,
) -> dict[str, Any]:
    normalized_scope_mode = normalize_scope_mode(scope_mode)
    if normalized_scope_mode == "video" and bvid:
        return {"scope": "video", "folder_id": folder_id, "bvid": bvid}
    if normalized_scope_mode == "folder" and folder_id is not None:
        return {"scope": "folder", "folder_id": folder_id, "bvid": None}
    if normalized_scope_mode == "global":
        return {"scope": "global", "folder_id": None, "bvid": None}
    if bvid:
        return {"scope": "video", "folder_id": folder_id, "bvid": bvid}
    if folder_id is not None:
        return {"scope": "folder", "folder_id": folder_id, "bvid": None}
    return {"scope": "global", "folder_id": None, "bvid": None}


def classify_query_intent(
    query: str,
    *,
    folder_id: int | None = None,
    bvid: str | None = None,
    scope_mode: str | None = None,
) -> dict[str, str]:
    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    payload = " ".join(str(query or "").lower().split())
    if not payload:
        return {"intent": "detail_qa", "scope": scope["scope"]}

    if not any(keyword in payload for keyword in SUMMARY_KEYWORDS):
        return {"intent": "detail_qa", "scope": scope["scope"]}

    has_folder_scope = any(keyword in payload for keyword in FOLDER_SCOPE_KEYWORDS)
    has_video_scope = any(keyword in payload for keyword in VIDEO_SCOPE_KEYWORDS)

    if has_video_scope and scope["bvid"]:
        return {"intent": "video_summary", "scope": "video"}
    if has_folder_scope:
        return {"intent": "folder_summary", "scope": "folder" if scope["folder_id"] is not None else "global"}
    if scope["scope"] == "video" and scope["bvid"]:
        return {"intent": "video_summary", "scope": "video"}
    if scope["scope"] == "folder":
        return {"intent": "folder_summary", "scope": "folder"}
    return {"intent": "folder_summary", "scope": "global"}


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


def compute_transcript_hash(transcript_text: str) -> str:
    return hashlib.sha256(str(transcript_text or "").encode("utf-8")).hexdigest()


def pack_summary_windows(
    segments: list[dict[str, Any]],
    *,
    max_chars: int = SUMMARY_WINDOW_CHARS,
) -> list[list[dict[str, Any]]]:
    windows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    safe_limit = max(int(max_chars), 1)

    for segment in segments:
        content = str(segment.get("content") or "").strip()
        if not content:
            continue
        next_chars = current_chars + len(content)
        if current and next_chars > safe_limit:
            windows.append(current)
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += len(content)

    if current:
        windows.append(current)
    return windows


def pack_summary_documents(
    documents: list[dict[str, Any]],
    *,
    max_docs: int = SUMMARY_GROUP_MAX_DOCS,
    max_chars: int = SUMMARY_GROUP_MAX_CHARS,
) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    safe_doc_limit = max(int(max_docs), 1)
    safe_char_limit = max(int(max_chars), 1)

    for document in documents:
        content = str(document.get("summary_text") or "").strip()
        if not content:
            continue
        next_chars = current_chars + len(content)
        if current and (len(current) >= safe_doc_limit or next_chars > safe_char_limit):
            groups.append(current)
            current = []
            current_chars = 0
        current.append(document)
        current_chars += len(content)

    if current:
        groups.append(current)
    return groups


def format_window_text(window: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, segment in enumerate(window, start=1):
        start_seconds = float(segment.get("start_seconds", 0) or 0)
        end_seconds = float(segment.get("end_seconds", start_seconds) or start_seconds)
        lines.append(
            "\n".join(
                [
                    f"[片段{index}] {seconds_to_timestamp(start_seconds)} - {seconds_to_timestamp(end_seconds)}",
                    str(segment.get("content") or "").strip(),
                ]
            )
        )
    return "\n\n".join(lines)


def build_summary_sources(
    documents: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for index, item in enumerate(documents, start=1):
        sources.append(
            {
                "ref_index": index,
                "video_title": str(item.get("video_title") or item.get("title") or item.get("bvid") or "未知视频"),
                "up_name": str(item.get("up_name") or "未知 UP"),
                "timestamp": "摘要",
                "jump_url": build_jump_url(str(item.get("bvid") or ""), 0),
                "excerpt": str(item.get("summary_text") or "").strip()[:160],
                "source_kind": "summary",
            }
        )
        if limit is not None and len(sources) >= limit:
            break
    return sources


async def ensure_video_summary(
    runtime: Runtime,
    bvid: str,
) -> dict[str, Any] | None:
    transcript = runtime.db.get_transcript(bvid)
    if not transcript:
        return None

    transcript_hash = compute_transcript_hash(str(transcript.get("transcript_text") or ""))
    existing = runtime.db.get_video_summary(bvid)
    if existing and str(existing.get("transcript_hash") or "") == transcript_hash and str(existing.get("summary_text") or "").strip():
        return existing

    video = runtime.db.get_video(bvid)
    segment_inputs = build_segment_inputs(list(transcript.get("segments") or []))
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
        return None

    total_chars = sum(len(str(segment.get("content") or "")) for segment in merged_segments)
    runtime.qwen.ensure_configured()
    if total_chars <= SUMMARY_DIRECT_CHARS:
        summary_text = await runtime.qwen.summarize_video(
            video_title=str((video or {}).get("title") or bvid),
            transcript_text=format_window_text(merged_segments),
        )
    else:
        windows = pack_summary_windows(merged_segments)
        window_summaries: list[str] = []
        for window in windows:
            summary = await runtime.qwen.summarize_video_window(
                video_title=str((video or {}).get("title") or bvid),
                transcript_text=format_window_text(window),
            )
            if summary:
                window_summaries.append(summary)
        if not window_summaries:
            return None
        summary_text = await runtime.qwen.reduce_video_summaries(
            video_title=str((video or {}).get("title") or bvid),
            window_summaries=window_summaries,
        )

    summary_text = str(summary_text or "").strip()
    if not summary_text:
        return None
    runtime.db.save_video_summary(
        bvid=bvid,
        transcript_hash=transcript_hash,
        summary_text=summary_text,
    )
    return runtime.db.get_video_summary(bvid)


async def load_summary_documents(
    runtime: Runtime,
    *,
    folder_id: int | None = None,
    bvid: str | None = None,
) -> list[dict[str, Any]]:
    if bvid:
        summary = await ensure_video_summary(runtime, bvid)
        return [summary] if summary else []

    documents = runtime.db.list_video_summaries(folder_id)
    if folder_id is None or len(documents) >= SUMMARY_AUTOGEN_FOLDER_LIMIT:
        return documents

    indexed_videos = [
        item
        for item in runtime.db.get_video_records(folder_id)
        if str(item.get("sync_status") or "") == "indexed"
    ]
    existing_bvids = {str(item.get("bvid") or "") for item in documents}
    generated = 0
    for video in indexed_videos:
        video_bvid = str(video.get("bvid") or "")
        if not video_bvid or video_bvid in existing_bvids:
            continue
        summary = await ensure_video_summary(runtime, video_bvid)
        if summary:
            generated += 1
            existing_bvids.add(video_bvid)
        if generated >= SUMMARY_AUTOGEN_FOLDER_LIMIT:
            break

    if generated > 0:
        return runtime.db.list_video_summaries(folder_id)
    return documents
