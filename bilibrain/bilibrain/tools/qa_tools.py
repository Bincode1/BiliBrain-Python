"""QA retrieval tools for the unified ReAct agent.

Provides search_knowledge_base (chunk-level) and search_video_summaries
(summary-level) as LangChain tools. Scope (folder_id, bvid) is captured
via closure, matching the pattern in tools/langchain_tools.py.
"""
from __future__ import annotations

from typing import Any, Callable

from langchain_core.tools import tool

from bilibrain.services.retrieval_support import (
    build_chunk_sources,
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
            "搜索当前视频知识库范围内的 chunk 级内容片段。"
            "适用于具体事实、定义、步骤、例子、代码、命令、时间点、原话等细节问题。"
            "必须先拿到真实返回内容再下结论；返回条目带 [n] 编号、视频标题、UP、时间点和片段正文，回答时按 [n] 引用。"
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
            sources = build_chunk_sources(matches, limit=20)
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
            "搜索当前视频知识库范围内的视频摘要。"
            "适用于收藏夹/多视频概览、主题归纳、跨视频对比、学习路线梳理、宏观总结等问题。"
            "只基于返回的摘要做归纳；返回条目带 [n] 编号、视频标题、UP 和摘要正文，回答时按 [n] 引用。"
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
