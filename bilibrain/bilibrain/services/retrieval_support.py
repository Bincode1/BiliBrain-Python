from __future__ import annotations

from typing import Any

from bilibrain.services.common import build_jump_url, seconds_to_timestamp
from bilibrain.services.summary import resolve_query_scope

SUMMARY_REDUCE_DOC_THRESHOLD = 12
SUMMARY_REDUCE_CHAR_THRESHOLD = 16000


async def describe_query_scope(
    runtime: Any, *, folder_id: int | None, bvid: str | None, scope_mode: str | None
) -> str:
    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    if scope["scope"] == "video" and scope.get("bvid"):
        video = await runtime.db.get_video(str(scope["bvid"])) or {}
        title = str(video.get("title") or scope["bvid"])
        return f"当前范围是单个视频：{title}（bvid={scope['bvid']}）。"
    if scope["scope"] == "folder" and scope.get("folder_id") is not None:
        folder = await runtime.db.get_folder(int(scope["folder_id"])) or {}
        title = str(folder.get("title") or f"收藏夹 {scope['folder_id']}")
        return f"当前范围是单个收藏夹：{title}（folder_id={scope['folder_id']}）。"
    return "当前范围是全部已入库内容。"


def should_reduce_summary_documents(documents: list[dict[str, Any]]) -> bool:
    total_chars = sum(len(str(item.get("summary_text") or "")) for item in documents)
    if (
        len(documents) <= SUMMARY_REDUCE_DOC_THRESHOLD
        and total_chars <= SUMMARY_REDUCE_CHAR_THRESHOLD
    ):
        return False
    return True


def build_chunk_sources(
    matches: list[dict[str, Any]], *, limit: int | None = None
) -> list[dict[str, str]]:
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


async def filter_indexed_hits(
    runtime: Any, hits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    statuses = await runtime.db.get_pipeline_overall_statuses(
        [str(hit.get("bvid") or "") for hit in hits]
    )
    filtered: list[dict[str, Any]] = []
    for hit in hits:
        if statuses.get(str(hit["bvid"]), "pending") == "indexed":
            filtered.append(hit)
    return filtered
