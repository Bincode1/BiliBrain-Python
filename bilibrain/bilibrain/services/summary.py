from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from bilibrain.services.common import build_segment_inputs
from bilibrain.services.common import build_jump_url, seconds_to_timestamp

if TYPE_CHECKING:
    from bilibrain.core.runtime import Runtime


SUMMARY_DIRECT_CHARS = 5000
SUMMARY_WINDOW_CHARS = 4500
SUMMARY_GROUP_MAX_DOCS = 8
SUMMARY_GROUP_MAX_CHARS = 12000
SUMMARY_AUTOGEN_FOLDER_LIMIT = 6

SUMMARY_KEYWORDS = frozenset(
    {
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
    }
)
FOLDER_SCOPE_KEYWORDS = frozenset(
    {
        "收藏夹",
        "这些视频",
        "文件夹",
        "这一组",
        "这组视频",
        "这一批视频",
    }
)
VIDEO_SCOPE_KEYWORDS = frozenset(
    {
        "这个视频",
        "这条视频",
        "这期视频",
        "本视频",
        "当前视频",
        "这期",
    }
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
        return {
            "intent": "folder_summary",
            "scope": "folder" if scope["folder_id"] is not None else "global",
        }
    if scope["scope"] == "video" and scope["bvid"]:
        return {"intent": "video_summary", "scope": "video"}
    if scope["scope"] == "folder":
        return {"intent": "folder_summary", "scope": "folder"}
    return {"intent": "folder_summary", "scope": "global"}


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
                "bvid": str(item.get("bvid") or ""),
                "video_title": str(
                    item.get("video_title")
                    or item.get("title")
                    or item.get("bvid")
                    or "未知视频"
                ),
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
    from bilibrain.graphs.summary import run_summary_graph

    return await run_summary_graph(runtime, bvid)


async def load_summary_documents(
    runtime: Runtime,
    *,
    folder_id: int | None = None,
    bvid: str | None = None,
) -> list[dict[str, Any]]:
    if bvid:
        summary = await ensure_video_summary(runtime, bvid)
        return [summary] if summary else []

    documents = await runtime.db.list_video_summaries(folder_id)
    if folder_id is None or len(documents) >= SUMMARY_AUTOGEN_FOLDER_LIMIT:
        return documents

    indexed_videos = [
        item
        for item in await runtime.db.get_video_records(folder_id)
        if str(item.get("sync_status") or "") == "indexed"
    ]
    existing_bvids = {str(item.get("bvid") or "") for item in documents}

    bvids_to_generate = []
    for video in indexed_videos:
        video_bvid = str(video.get("bvid") or "")
        if not video_bvid or video_bvid in existing_bvids:
            continue
        bvids_to_generate.append(video_bvid)
        if len(bvids_to_generate) >= SUMMARY_AUTOGEN_FOLDER_LIMIT:
            break

    if not bvids_to_generate:
        return documents

    import asyncio

    results = await asyncio.gather(
        *[ensure_video_summary(runtime, bvid) for bvid in bvids_to_generate],
        return_exceptions=True,
    )

    for bvid, summary in zip(bvids_to_generate, results):
        if summary and not isinstance(summary, Exception):
            existing_bvids.add(bvid)

    return await runtime.db.list_video_summaries(folder_id)
