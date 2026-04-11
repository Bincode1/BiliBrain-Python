"""QA retrieval tools for the unified ReAct agent.

Provides search_knowledge_base (chunk-level) and search_video_summaries
(summary-level) as LangChain tools. Scope (folder_id, bvid) is captured
via closure, matching the pattern in tools/langchain_tools.py.
"""
from __future__ import annotations

from typing import Any, Callable

from langchain_core.tools import tool

from bilibrain.graphs.qa.helpers import (
    build_sources,
    filter_indexed_hits,
    should_reduce_summary_documents,
)
from bilibrain.services.common import rerank_search_hits, seconds_to_timestamp
from bilibrain.services.summary import (
    build_summary_sources,
    load_summary_documents,
)


def build_qa_retrieval_tools(
    runtime,
    *,
    folder_id: int | None = None,
    bvid: str | None = None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    retrieval_top_k: int = 40,
    rerank_top_k: int = 10,
):
    """Build QA retrieval LangChain tools scoped to the given folder/video."""

    def _emit_tool_start(name: str, summary: dict[str, Any]) -> None:
        if event_callback is not None:
            event_callback("tool", {"phase": "start", "name": name, "summary": summary})

    def _emit_tool_finish(name: str, *, ok: bool, error: str | None = None) -> None:
        if event_callback is not None:
            event_callback("tool", {"phase": "finish", "name": name, "ok": ok, "error": error})

    @tool(
        "search_knowledge_base",
        description=(
            "搜索视频知识库，返回与查询相关的具体内容片段。"
            "适用于：查具体细节、事实、步骤、定义、时间点。"
            "返回带编号的资料列表，回答时用【n】引用编号。"
        ),
    )
    async def search_knowledge_base(query: str) -> str:
        _emit_tool_start("search_knowledge_base", {"query": query})
        try:
            # 1. Generate embedding
            runtime.embedder.ensure_configured()
            embeddings = await runtime.embedder.embed_texts([query])
            query_embedding = embeddings[0]

            # 2. Hybrid search
            hits = await runtime.vector_store.ahybrid_search(
                query_embedding=query_embedding,
                query_text=query,
                folder_id=folder_id,
                bvid=bvid,
                limit=retrieval_top_k,
            )

            # 3. Filter to indexed videos only
            filtered = await filter_indexed_hits(runtime, hits)
            if not filtered:
                _emit_tool_finish("search_knowledge_base", ok=True)
                return "知识库中没有找到与查询相关的内容。"

            # 4. Rerank
            matches = rerank_search_hits(query=query, hits=filtered, limit=rerank_top_k)

            # 5. Build sources and context text
            sources = build_sources(matches, limit=20)
            lines = []
            for idx, item in enumerate(matches, start=1):
                lines.append(
                    f"[{idx}] {item['video_title']} | {item.get('up_name', 'Unknown')} "
                    f"@ {seconds_to_timestamp(item['start_seconds'])}: {item['content']}"
                )
            context_text = "\n".join(lines)

            # Emit sources via callback for SSE persistence
            if event_callback:
                event_callback("sources", {"sources": sources})

            _emit_tool_finish("search_knowledge_base", ok=True)
            return context_text
        except Exception as exc:
            _emit_tool_finish("search_knowledge_base", ok=False, error=str(exc))
            raise

    @tool(
        "search_video_summaries",
        description=(
            "搜索视频摘要，返回收藏夹/范围内视频的概要内容。"
            "适用于：做总结、概括、归纳、对比、梳理整体观点。"
            "返回带编号的摘要列表，回答时用【n】引用编号。"
        ),
    )
    async def search_video_summaries(query: str) -> str:
        _emit_tool_start("search_video_summaries", {"query": query})
        try:
            # 1. Load summary documents
            documents = await load_summary_documents(
                runtime, folder_id=folder_id, bvid=bvid,
            )
            if not documents:
                _emit_tool_finish("search_video_summaries", ok=True)
                return "当前范围内没有可用的视频摘要。"

            # 2. Reduce if too many
            if should_reduce_summary_documents(documents):
                reduced = await runtime.qwen.reduce_summary_documents(
                    query=query, documents=documents,
                )
                _emit_tool_finish("search_video_summaries", ok=True)
                return f"[1] 综合摘要：\n{reduced}"

            # 3. Build sources and context text
            sources = build_summary_sources(documents, limit=20)
            lines = []
            for idx, item in enumerate(documents, start=1):
                lines.append(
                    f"[{idx}] {item.get('video_title', '未知视频')} | {item.get('up_name', 'Unknown')}\n"
                    f"{str(item.get('summary_text') or '').strip()}"
                )
            context_text = "\n\n".join(lines)

            # Emit sources via callback for SSE persistence
            if event_callback:
                event_callback("sources", {"sources": sources})

            _emit_tool_finish("search_video_summaries", ok=True)
            return context_text
        except Exception as exc:
            _emit_tool_finish("search_video_summaries", ok=False, error=str(exc))
            raise

    return [search_knowledge_base, search_video_summaries]
