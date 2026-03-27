from __future__ import annotations

import re
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from bilibrain.graphs.qa.helpers import build_sources as build_chunk_sources
from bilibrain.graphs.qa.helpers import describe_query_scope, filter_indexed_hits
from bilibrain.graphs.research.state import ResearchState
from bilibrain.services.common import rerank_search_hits
from bilibrain.services.summary import build_summary_sources, resolve_query_scope
from bilibrain.tools.contracts import ToolApprovalMode

MAX_RESEARCH_ROUNDS = 1
MAX_WEB_SOURCES_PER_ROUND = 5
MAX_SEARCH_QUERIES_PER_ROUND = 2
TECH_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+#/-]{1,}")
TECH_TERM_STOPWORDS = {"what", "which", "when", "where", "with", "from", "than", "this", "that", "does"}
INTENT_KEYWORD_RULES = (
    ("区别", ("区别", "不同", "差异", "对比")),
    ("源码", ("源码", "source code")),
    ("模块", ("模块", "组成", "结构")),
    ("架构", ("架构", "原理", "机制")),
    ("学习", ("学习", "入门", "上手", "开始", "怎么学", "如何学", "教程")),
    ("实现", ("实现", "实现方式")),
    ("用法", ("用法", "使用", "怎么用")),
)


def _merge_timings(state: ResearchState, **timings: float) -> dict[str, float]:
    merged = dict(state.get("timings") or {})
    for key, value in timings.items():
        merged[key] = round(float(value), 3)
    return merged


def _stream_custom(payload: dict[str, Any]) -> None:
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        writer = None
    if writer is not None:
        writer(payload)


def _reindex_sources(items: list[dict[str, Any]], *, start: int = 1) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    next_ref = max(int(start), 1)
    for item in items:
        normalized.append({**item, "ref_index": next_ref})
        next_ref += 1
    return normalized


def _normalize_short_queries(values: list[str], *, fallback: str, limit: int = 6) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        query = " ".join(str(item or "").split()).strip()
        if not query:
            continue
        if len(query) > 72:
            query = query[:72].strip()
        if query in seen:
            continue
        seen.add(query)
        normalized.append(query)
        if len(normalized) >= max(int(limit), 1):
            break
    if not normalized:
        return [str(fallback or "").strip()]
    return normalized


def _split_lines(value: str) -> list[str]:
    items: list[str] = []
    for raw in str(value or "").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line[:2].isdigit() and len(line) > 2 and line[2] in {".", "、"}:
            line = line[3:].strip()
        elif line[:1].isdigit() and len(line) > 1 and line[1] in {".", "、"}:
            line = line[2:].strip()
        elif line.startswith(("-", "*")):
            line = line[1:].strip()
        if line:
            items.append(line)
    return items


def _extract_technical_terms(query: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in TECH_TERM_RE.findall(str(query or "")):
        for part in re.split(r"[\\/]", raw):
            cleaned = part.strip().strip("()[]{}<>,.;:!?\"'`")
            if len(cleaned) < 2:
                continue
            lowered = cleaned.lower()
            if lowered in TECH_TERM_STOPWORDS or lowered in seen:
                continue
            seen.add(lowered)
            tokens.append(cleaned)
    return tokens


def _extract_intent_keywords(query: str, *, limit: int = 3) -> list[str]:
    matches: list[tuple[int, str]] = []
    payload = str(query or "")
    for label, patterns in INTENT_KEYWORD_RULES:
        positions = [payload.find(pattern) for pattern in patterns if payload.find(pattern) >= 0]
        if positions:
            matches.append((min(positions), label))
    matches.sort(key=lambda item: item[0])
    return [label for _, label in matches[: max(int(limit), 1)]]


def _build_dual_search_queries(
    *,
    query: str,
    primary_hint: str = "",
    secondary_hint: str = "",
) -> list[str]:
    tech_terms = _extract_technical_terms(query)
    intent_keywords = _extract_intent_keywords(query)

    primary_query = tech_terms[0] if tech_terms else str(primary_hint or query).strip()

    secondary_parts: list[str] = []
    if tech_terms:
        secondary_parts.extend(tech_terms[:2])
    if intent_keywords:
        secondary_parts.extend(intent_keywords)
    secondary_query = " ".join(part for part in secondary_parts if str(part or "").strip()).strip()
    if not secondary_query:
        secondary_query = str(secondary_hint or "").strip()

    queries = _normalize_short_queries(
        [primary_query, secondary_query],
        fallback=query,
        limit=MAX_SEARCH_QUERIES_PER_ROUND,
    )
    if len(queries) < MAX_SEARCH_QUERIES_PER_ROUND and str(secondary_hint or "").strip():
        queries = _normalize_short_queries(
            [*queries, str(secondary_hint).strip()],
            fallback=query,
            limit=MAX_SEARCH_QUERIES_PER_ROUND,
        )
    return queries


def _build_kb_lookup_query(query: str) -> str:
    queries = _build_dual_search_queries(query=query)
    if len(queries) >= 2:
        return queries[1]
    return queries[0]


async def resolve_scope_and_conversation(state: ResearchState) -> dict[str, Any]:
    runtime = state["runtime"]
    folder_id = state.get("folder_id")
    bvid = state.get("bvid")
    scope_mode = state.get("scope_mode")
    conversation_id = state.get("conversation_id")

    if conversation_id is None:
        conversation = runtime.db.create_chat_conversation(None)
    else:
        conversation = runtime.db.get_chat_conversation(int(conversation_id))
        if not conversation:
            conversation = runtime.db.create_chat_conversation(None)

    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    resolved_conversation_id = int(conversation["conversation_id"]) if conversation else None
    _stream_custom({"_status": "正在准备深度研究范围..."})

    return {
        "scope": scope,
        "conversation": conversation,
        "conversation_id": resolved_conversation_id,
        "folder_id": scope["folder_id"] if scope["scope"] == "folder" else None,
        "current_step": "scope_resolved",
        "_conversation_id": resolved_conversation_id,
        "_status": "正在准备深度研究范围...",
    }


async def append_user_message(state: ResearchState) -> dict[str, Any]:
    runtime = state["runtime"]
    conversation_id = state.get("conversation_id")
    query = state["query"]
    _stream_custom({"_status": "正在记录研究问题..."})
    if conversation_id is None:
        return {"user_message": None, "current_step": "user_message_appended"}
    user_message = runtime.db.append_chat_message(conversation_id, "user", query)
    return {
        "user_message": user_message,
        "current_step": "user_message_appended",
    }


async def prepare_research_workspace(state: ResearchState) -> dict[str, Any]:
    runtime = state["runtime"]
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")
    _stream_custom({"_status": "正在准备研究工作区..."})
    conversation_id = state.get("conversation_id")
    workspace = runtime.tool_service.create_workspace(
        feature_name="deep-research",
        conversation_id=conversation_id,
        title=f"Deep Research {conversation_id or 'session'}",
        actor="research-agent",
    )
    return {
        "workspace": workspace,
        "current_step": "workspace_prepared",
    }


async def load_kb_snapshot(state: ResearchState) -> dict[str, Any]:
    started = perf_counter()
    runtime = state["runtime"]
    query = state["query"]
    scope = state.get("scope") or {}
    kb_query = _build_kb_lookup_query(query)

    if scope.get("scope") == "video" and scope.get("bvid"):
        summary_docs = runtime.db.search_video_summaries(kb_query, bvid=str(scope["bvid"]), limit=6)
    elif scope.get("scope") == "folder" and scope.get("folder_id") is not None:
        summary_docs = runtime.db.search_video_summaries(kb_query, folder_id=int(scope["folder_id"]), limit=6)
    else:
        summary_docs = runtime.db.search_video_summaries(kb_query, limit=6)

    chunk_hits: list[dict[str, Any]] = []
    try:
        runtime.embedder.ensure_configured()
        query_embedding = (await runtime.embedder.embed_texts([kb_query]))[0]
        hits = runtime.vector_store.hybrid_search(
            query_embedding=query_embedding,
            query_text=kb_query,
            folder_id=scope["folder_id"] if scope.get("scope") == "folder" else None,
            bvid=scope["bvid"] if scope.get("scope") == "video" else None,
            limit=12,
        )
        filtered_hits = filter_indexed_hits(runtime, hits)
        chunk_hits = rerank_search_hits(query=kb_query, hits=filtered_hits, limit=6)
    except Exception:
        chunk_hits = []

    covered_points: list[str] = []
    for item in summary_docs[:4]:
        title = str(item.get("video_title") or item.get("bvid") or "未知视频").strip()
        excerpt = str(item.get("summary_text") or "").strip().replace("\n", " ")
        if title:
            covered_points.append(f"[候选摘要] {title}: {excerpt[:120]}".strip())
    for item in chunk_hits[:3]:
        title = str(item.get("video_title") or item.get("bvid") or "未知视频").strip()
        excerpt = str(item.get("content") or "").strip().replace("\n", " ")
        if title:
            covered_points.append(f"[候选片段] {title}: {excerpt[:100]}".strip())

    kb_sources = _reindex_sources(
        [
            *build_summary_sources(summary_docs[:4], limit=4),
            *build_chunk_sources(chunk_hits[:4], limit=4),
        ]
    )

    kb_snapshot = {
        "scope": scope,
        "summary_docs": [
            {
                "bvid": str(item.get("bvid") or ""),
                "video_title": str(item.get("video_title") or ""),
                "up_name": str(item.get("up_name") or ""),
                "summary_text": str(item.get("summary_text") or "").strip(),
            }
            for item in summary_docs[:6]
        ],
        "chunk_hits": [
            {
                "bvid": str(item.get("bvid") or ""),
                "video_title": str(item.get("video_title") or ""),
                "up_name": str(item.get("up_name") or ""),
                "content": str(item.get("content") or "").strip(),
                "start_seconds": float(item.get("start_seconds") or 0),
                "score": float(item.get("score") or 0),
            }
            for item in chunk_hits
        ],
        "covered_points": covered_points,
        "coverage_notes": f"知识库按问题关键词“{kb_query}”预查发现 {len(summary_docs)} 条候选摘要、{len(chunk_hits)} 个候选片段。",
    }
    _stream_custom(
        {
            "_status": "已完成知识库预查，正在拆解研究任务...",
            "_agent": {
                "agent": "kb_lookup",
                "status": "completed",
                "message": kb_snapshot["coverage_notes"],
            },
        }
    )
    return {
        "kb_snapshot": kb_snapshot,
        "kb_sources": kb_sources,
        "current_step": "kb_snapshot_loaded",
        "timings": _merge_timings(state, kb_snapshot_ms=(perf_counter() - started) * 1000),
    }


async def orchestrate_subtasks(state: ResearchState) -> dict[str, Any]:
    started = perf_counter()
    runtime = state["runtime"]
    query = state["query"]
    scope = state.get("scope") or {}
    kb_snapshot = state.get("kb_snapshot") or {}
    runtime.qwen.ensure_configured()
    scope_description = describe_query_scope(
        runtime,
        folder_id=scope.get("folder_id"),
        bvid=scope.get("bvid"),
        scope_mode=scope.get("scope"),
    )
    brief = await runtime.qwen.understand_research_query(
        query=query,
        scope_description=scope_description,
        kb_snapshot=kb_snapshot,
    )
    key_aspects = _split_lines(str(brief.key_aspects_text or ""))
    if not key_aspects:
        key_aspects = [str(query).strip()]
    subtasks = [
        {
            "task_id": f"aspect-{index}",
            "title": aspect,
            "objective": "需要在最终报告中覆盖的关键维度",
            "search_queries": [],
            "already_covered": [],
            "do_not_repeat": "",
        }
        for index, aspect in enumerate(key_aspects, start=1)
    ]
    current_queries = _build_dual_search_queries(
        query=query,
        primary_hint=str(brief.primary_query or "").strip(),
        secondary_hint=str(brief.secondary_query or "").strip(),
    )
    _stream_custom(
        {
            "_status": f"研究问题已解析，识别出 {len(subtasks)} 个关键维度，并生成 {len(current_queries)} 条检索词。",
            "_mode": "research",
            "_research_plan": {"task_count": len(subtasks), "tasks": subtasks},
            "_agent": {
                "agent": "orchestrator",
                "status": "completed",
                "message": "准备进入双角度检索。",
            },
        }
    )
    return {
        "research_brief": brief.model_dump(),
        "current_queries": current_queries,
        "retrieval_round": 0,
        "research_plan": {
            "research_goal": brief.research_goal,
            "subtasks": subtasks,
        },
        "subtasks": subtasks,
        "current_step": "subtasks_orchestrated",
        "timings": _merge_timings(state, orchestrator_ms=(perf_counter() - started) * 1000),
    }


def _domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


async def run_retrieval(state: ResearchState) -> dict[str, Any]:
    started = perf_counter()
    runtime = state["runtime"]
    workspace = state.get("workspace") or {}
    workspace_id = str(workspace.get("workspace_id") or "")
    if runtime.tool_service is None or not workspace_id:
        raise RuntimeError("Research workspace is not available.")

    current_round = int(state.get("retrieval_round") or 0) + 1
    queries = _normalize_short_queries(
        [str(item).strip() for item in list(state.get("current_queries") or []) if str(item).strip()],
        fallback=state["query"],
        limit=MAX_SEARCH_QUERIES_PER_ROUND,
    )
    existing_sources = list(state.get("sources") or [])
    all_sources: list[dict[str, Any]] = _filter_citable_sources(existing_sources)
    next_ref = len(all_sources) + 1
    seen_urls: set[str] = {str(item.get("url") or item.get("jump_url") or "").strip() for item in all_sources}
    retrieval_sources: list[dict[str, Any]] = []
    retrieval_error = ""

    total_queries = len(queries)
    for index, search_query in enumerate(queries, start=1):
        _stream_custom({"_status": f"正在执行第 {index}/{total_queries} 次检索：{search_query}"})
        candidates: list[dict[str, Any]] = []
        before_count = len(all_sources)
        per_query_added = 0
        research_retriever = getattr(runtime, "research_retriever", None)
        if research_retriever is None or not getattr(research_retriever, "enabled", False):
            retrieval_error = "Tavily MCP 未配置或未启用，外部网页检索已跳过。"
            break
        try:
            candidates = list(
                await research_retriever.retrieve(
                    search_query,
                    max_results=MAX_WEB_SOURCES_PER_ROUND,
                )
            )
        except Exception as exc:
            retrieval_error = f"Tavily MCP 检索失败：{str(exc).strip() or 'unknown error'}"
            break

        for candidate in candidates:
            url = str(candidate.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            page_title = str(candidate.get("title") or "").strip()
            page_text = str(candidate.get("content") or candidate.get("snippet") or "").strip()
            final_url = url
            if not page_text:
                continue
            source = {
                "ref_index": next_ref,
                "title": page_title or final_url,
                "url": final_url,
                "jump_url": final_url,
                "excerpt": page_text[:220],
                "source_kind": "web",
                "timestamp": "网页",
                "provider": str(candidate.get("provider") or "tavily_mcp"),
                "domain": str(candidate.get("domain") or _domain_from_url(final_url)).strip(),
            }
            next_ref += 1
            retrieval_sources.append(
                {
                    "query": search_query,
                    "title": page_title or final_url,
                    "url": final_url,
                    "content": page_text,
                    "domain": source["domain"],
                    "provider": source["provider"],
                    "ref_index": source["ref_index"],
                }
            )
            all_sources.append(source)
            per_query_added += 1
            if per_query_added >= MAX_WEB_SOURCES_PER_ROUND:
                break
        added_count = len(all_sources) - before_count
        _stream_custom(
            {
                "_agent": {
                    "agent": "retrieval",
                    "status": "completed",
                    "message": f"{search_query}，新增 {max(added_count, 0)} 个网页来源。",
                    "completed": index,
                    "total": total_queries,
                },
            }
        )

    _stream_custom(
        {
            "_status": retrieval_error or f"双角度检索已完成，累计 {len(all_sources)} 个网页来源。",
        }
    )
    return {
        "retrieval_results": [
            {
                "task_id": f"round-{current_round}",
                "title": f"第 {current_round} 轮综合检索",
                "objective": state["query"],
                "queries": queries,
                "sources": retrieval_sources,
            }
        ],
        "sources": all_sources,
        "retrieval_round": current_round,
        "retrieval_error": retrieval_error,
        "current_step": "retrieval_completed",
        "timings": _merge_timings(state, retrieval_ms=(perf_counter() - started) * 1000),
    }


def _format_kb_snapshot_text(kb_snapshot: dict[str, Any]) -> str:
    lines: list[str] = [str(kb_snapshot.get("coverage_notes") or "").strip()]
    for item in list(kb_snapshot.get("covered_points") or [])[:8]:
        value = str(item or "").strip()
        if value:
            lines.append(f"- {value}")
    return "\n".join(line for line in lines if line)


def _format_retrieval_materials(task: dict[str, Any]) -> str:
    lines: list[str] = []
    for index, source in enumerate(list(task.get("sources") or []), start=1):
        lines.append(
            "\n".join(
                [
                    f"[来源 {index}] {str(source.get('title') or source.get('url') or '').strip()}",
                    str(source.get("url") or "").strip(),
                    str(source.get("content") or "").strip(),
                ]
            )
        )
    return "\n\n".join(lines)


def _filter_citable_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in sources if str(item.get("source_kind") or "").strip() == "web"]


def _format_all_source_materials(sources: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in sources:
        excerpt = str(item.get("excerpt") or "").strip()
        if not excerpt:
            continue
        title = str(item.get("title") or item.get("video_title") or item.get("jump_url") or "").strip()
        jump_url = str(item.get("jump_url") or item.get("url") or "").strip()
        source_kind = str(item.get("source_kind") or "source").strip()
        lines.append(
            "\n".join(
                [
                    f"【{int(item.get('ref_index') or 0)}】[{source_kind}] {title}",
                    jump_url,
                    excerpt,
                ]
            )
        )
    return "\n\n".join(lines)


async def analyze_retrievals(state: ResearchState) -> dict[str, Any]:
    started = perf_counter()
    runtime = state["runtime"]
    kb_snapshot = state.get("kb_snapshot") or {}
    kb_snapshot_text = _format_kb_snapshot_text(kb_snapshot)
    research_brief = state.get("research_brief") or {}
    materials_text = _format_all_source_materials(_filter_citable_sources(list(state.get("sources") or [])))
    if not materials_text:
        analysis = "当前没有形成可引用的外部网页证据，本轮不把知识库候选资料直接写成事实结论。"
    else:
        analysis = await runtime.qwen.analyze_research_evidence(
            query=state["query"],
            research_goal=str(research_brief.get("research_goal") or state["query"]).strip(),
            key_aspects=_split_lines(str(research_brief.get("key_aspects_text") or "")),
            kb_snapshot_text=kb_snapshot_text,
            materials_text=materials_text,
        )
    analysis_results = [
        {
            "task_id": f"round-{int(state.get('retrieval_round') or 1)}",
            "title": "综合研究分析",
            "analysis": str(analysis or "").strip(),
        }
    ]

    _stream_custom(
        {
            "_status": "本次证据分析完成。",
            "_agent": {
                "agent": "analysis",
                "status": "completed",
                "message": "已完成当前证据池的综合分析。",
                "completed": int(state.get("retrieval_round") or 1),
                "total": MAX_RESEARCH_ROUNDS,
            },
        }
    )
    return {
        "analysis_results": analysis_results,
        "current_step": "analysis_completed",
        "timings": _merge_timings(state, analysis_ms=(perf_counter() - started) * 1000),
    }


def _format_analysis_text(analysis_results: list[dict[str, Any]]) -> str:
    sections: list[str] = []
    for item in analysis_results:
        title = str(item.get("title") or item.get("task_id") or "未命名任务").strip()
        analysis = str(item.get("analysis") or "").strip()
        if analysis:
            sections.append(f"## {title}\n{analysis}")
    return "\n\n".join(sections)


def _format_sources_text(sources: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in sources:
        ref_index = int(item.get("ref_index") or 0)
        title = str(item.get("title") or item.get("video_title") or item.get("jump_url") or "").strip()
        url = str(item.get("jump_url") or item.get("url") or "").strip()
        source_kind = str(item.get("source_kind") or "").strip() or "source"
        if title or url:
            lines.append(f"【{ref_index}】 [{source_kind}] {title} | {url}")
    return "\n".join(lines)


async def write_report(state: ResearchState) -> dict[str, Any]:
    started = perf_counter()
    runtime = state["runtime"]
    kb_snapshot_text = _format_kb_snapshot_text(state.get("kb_snapshot") or {})
    analysis_text = _format_analysis_text(state.get("analysis_results") or [])
    gap_text = str(state.get("gap_summary") or "").strip()
    sources_text = _format_sources_text(_filter_citable_sources(list(state.get("sources") or [])))
    answer_text = ""

    try:
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
    except Exception:
        writer = None

    async for delta in runtime.qwen.stream_research_report(
        query=state["query"],
        kb_snapshot_text=kb_snapshot_text,
        analysis_text=analysis_text,
        gap_text=gap_text,
        sources_text=sources_text,
    ):
        answer_text += delta
        if writer:
            writer({"_answer_token": delta})

    _stream_custom(
        {
            "_status": "Writer Agent 已完成研究报告生成。",
            "_agent": {
                "agent": "writer",
                "status": "completed",
                "message": "研究报告已生成。",
            },
        }
    )
    return {
        "answer_text": answer_text.strip(),
        "current_step": "report_written",
        "timings": _merge_timings(state, writer_ms=(perf_counter() - started) * 1000),
    }


async def append_assistant_message(state: ResearchState) -> dict[str, Any]:
    runtime = state["runtime"]
    conversation_id = state.get("conversation_id")
    answer_text = str(state.get("answer_text") or "").strip()
    if not conversation_id or not answer_text:
        return {"assistant_message": None, "current_step": "assistant_message_appended"}
    assistant_message = runtime.db.append_chat_message(
        int(conversation_id),
        "assistant",
        answer_text,
        sources=_filter_citable_sources(list(state.get("sources") or [])),
        answer_mode="research",
        route_mode="research",
    )
    return {
        "assistant_message": assistant_message,
        "current_step": "assistant_message_appended",
    }
