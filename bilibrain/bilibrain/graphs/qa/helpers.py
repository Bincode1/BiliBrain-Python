from __future__ import annotations

from typing import Any

from bilibrain.services.common import build_jump_url, seconds_to_timestamp
from bilibrain.services.summary import (
    resolve_query_scope,
)

SUMMARY_REDUCE_DOC_THRESHOLD = 12
SUMMARY_REDUCE_CHAR_THRESHOLD = 16000

PLANNER_HINT_KEYWORDS = (
    "前面",
    "刚才",
    "之前",
    "上一轮",
    "上一次",
    "上个",
    "那个",
    "这个",
    "第二点",
    "第三点",
    "继续",
    "展开",
    "补充",
    "总结",
    "概括",
    "归纳",
    "梳理",
)


def should_use_planner(query: str) -> bool:
    payload = " ".join(str(query or "").lower().split())
    if not payload:
        return False
    return any(keyword in payload for keyword in PLANNER_HINT_KEYWORDS)


def describe_query_scope(runtime: Any, *, folder_id: int | None, bvid: str | None, scope_mode: str | None) -> str:
    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    if scope["scope"] == "video" and scope.get("bvid"):
        video = runtime.db.get_video(str(scope["bvid"])) or {}
        title = str(video.get("title") or scope["bvid"])
        return f"当前范围是单个视频：{title}（bvid={scope['bvid']}）。"
    if scope["scope"] == "folder" and scope.get("folder_id") is not None:
        folder = runtime.db.get_folder(int(scope["folder_id"])) or {}
        title = str(folder.get("title") or f"收藏夹 {scope['folder_id']}")
        return f"当前范围是单个收藏夹：{title}（folder_id={scope['folder_id']}）。"
    return "当前范围是全部已入库内容。"


def build_empty_answer_message(scope: dict[str, Any]) -> str:
    if scope.get("scope") == "video":
        return "当前视频还没有可检索内容。请先完成处理，或切换到收藏夹 / 全部范围。"
    if scope.get("scope") == "folder":
        return "当前收藏夹还没有可检索内容。请先处理其中至少一个视频，或切换到全部范围。"
    return "当前还没有可检索内容。请先完成至少一个视频的处理。"


def resolve_effective_history(use_history: bool, context: dict[str, Any]) -> list[dict[str, Any]]:
    if not use_history:
        return []
    return context.get("recent_history") or []


def resolve_effective_memory_text(use_history: bool, context: dict[str, Any]) -> str:
    if not use_history:
        return ""
    return str(context.get("memory_text") or "").strip()


def _summary_total_chars(documents: list[dict[str, Any]]) -> int:
    return sum(len(str(item.get("summary_text") or "")) for item in documents)


def should_reduce_summary_documents(documents: list[dict[str, Any]]) -> bool:
    if len(documents) <= SUMMARY_REDUCE_DOC_THRESHOLD and _summary_total_chars(documents) <= SUMMARY_REDUCE_CHAR_THRESHOLD:
        return False
    return True


def build_sources(matches: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for index, item in enumerate(matches, start=1):
        sources.append(
            {
                "ref_index": index,
                "bvid": str(item.get("bvid") or ""),
                "chunk_id": str(item.get("chunk_id") or ""),
                "video_title": item["video_title"],
                "up_name": item.get("up_name") or "未知 UP",
                "timestamp": seconds_to_timestamp(item["start_seconds"]),
                "jump_url": build_jump_url(item["bvid"], item["start_seconds"]),
                "excerpt": str(item.get("content") or "").strip()[:160],
                "source_kind": "chunk",
            }
        )
        if limit is not None and len(sources) >= limit:
            break
    return sources


def filter_indexed_hits(runtime: Any, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    statuses = runtime.db.get_pipeline_overall_statuses([str(hit.get("bvid") or "") for hit in hits])
    filtered: list[dict[str, Any]] = []
    for hit in hits:
        if statuses.get(str(hit["bvid"]), "pending") == "indexed":
            filtered.append(hit)
    return filtered
