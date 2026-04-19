from __future__ import annotations

import logging
from time import perf_counter
from typing import Any
from langchain_core.messages import AIMessage, HumanMessage

logger = logging.getLogger(__name__)

from bilibrain.graphs.qa.helpers import (
    build_empty_answer_message,
    build_sources,
    describe_query_scope,
    filter_indexed_hits,
    resolve_effective_history,
    resolve_effective_memory_text,
    should_reduce_summary_documents,
    should_use_planner,
)
from bilibrain.graphs.qa.state import QAState
from bilibrain.services.citations import normalize_answer_citations
from bilibrain.services.chat_memory import (
    build_conversation_context,
    compact_conversation_context,
    refresh_context_stats_after_message,
    should_compact_context,
)
from bilibrain.services.chat_storage import (
    append_chat_message_dual_write,
    ensure_chat_session,
)
from bilibrain.services.common import rerank_search_hits
from bilibrain.services.summary import (
    build_summary_sources,
    classify_query_intent,
    load_summary_documents,
    pack_summary_documents,
    resolve_query_scope,
)
from bilibrain.graphs.qa.state import QAState
from bilibrain.services.citations import normalize_answer_citations
from bilibrain.services.chat_memory import (
    build_conversation_context,
    compact_conversation_context,
    refresh_context_stats_after_message,
    should_compact_context,
)
from bilibrain.services.common import rerank_search_hits
from bilibrain.services.summary import (
    build_summary_sources,
    classify_query_intent,
    load_summary_documents,
    pack_summary_documents,
    resolve_query_scope,
)


def _execution_policy(state: QAState) -> dict[str, Any]:
    raw = dict(state.get("execution_policy") or {})
    return {
        "persist_messages": bool(raw.get("persist_messages", True)),
        "load_history": bool(raw.get("load_history", True)),
        "planner_enabled": bool(raw.get("planner_enabled", True)),
        "retrieval_top_k": max(int(raw.get("retrieval_top_k") or 40), 1),
        "rerank_top_k": max(int(raw.get("rerank_top_k") or 10), 1),
    }


def _merge_timings(state: QAState, **timings: float) -> dict[str, float]:
    merged = dict(state.get("timings") or {})
    for key, value in timings.items():
        merged[key] = round(float(value), 3)
    return merged


async def resolve_scope_and_conversation(state: QAState) -> dict[str, Any]:
    runtime = state["runtime"]
    query = state["query"]
    logger.info("[QA] Resolving scope for query: %s", query[:80])
    folder_id = state.get("folder_id")
    bvid = state.get("bvid")
    scope_mode = state.get("scope_mode")
    conversation_id = state.get("conversation_id")
    policy = _execution_policy(state)

    if not policy["persist_messages"] and conversation_id is None:
        conversation = None
    else:
        conversation = await ensure_chat_session(
            runtime,
            conversation_id=conversation_id,
            folder_id=None,
            title=None,
        )
        if not conversation and policy["persist_messages"]:
            conversation = await ensure_chat_session(
                runtime,
                conversation_id=None,
                folder_id=None,
                title=None,
            )

    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    resolved_conversation_id = conversation["conversation_id"] if conversation else None

    return {
        "scope": scope,
        "conversation": conversation,
        "conversation_id": resolved_conversation_id,
        "folder_id": scope["folder_id"] if scope["scope"] == "folder" else None,
        "current_step": "scope_resolved",
        "_conversation_id": resolved_conversation_id,
        "_status": "正在解析查询范围...",
    }


async def load_conversation_context(state: QAState) -> dict[str, Any]:
    runtime = state["runtime"]
    conversation_id = state["conversation_id"]
    policy = _execution_policy(state)

    if not policy["load_history"] or conversation_id is None:
        return {
            "context": {
                "recent_history": [],
                "memory_text": "",
            },
            "memory_text": "",
            "recent_history": [],
            "current_step": "context_loaded",
            "_status": "评测模式：跳过历史上下文加载...",
        }

    context = await build_conversation_context(runtime, conversation_id=conversation_id)

    return {
        "context": {
            "recent_history": context.recent_history,
            "memory_text": context.memory_text,
        },
        "memory_text": context.memory_text,
        "recent_history": context.recent_history,
        "current_step": "context_loaded",
        "_status": "正在加载对话上下文...",
    }


async def compact_memory_if_needed(state: QAState) -> dict[str, Any]:
    runtime = state["runtime"]
    conversation_id = state["conversation_id"]
    context = state.get("context") or {}
    policy = _execution_policy(state)

    if not policy["load_history"] or conversation_id is None:
        return {
            "context": {
                "recent_history": context.get("recent_history") or [],
                "memory_text": str(context.get("memory_text") or ""),
            },
            "memory_text": str(context.get("memory_text") or ""),
            "recent_history": context.get("recent_history") or [],
            "current_step": "memory_compacted",
            "_status": "评测模式：跳过上下文压缩...",
        }

    from bilibrain.services.chat_memory import ConversationContext

    context_obj = ConversationContext(
        recent_history=context.get("recent_history") or [],
        memory_text=context.get("memory_text") or "",
        compacted_until_message_id=None,
        recent_start_message_id=None,
        estimated_tokens=0,
        memory_token_estimate=0,
        uncompacted_token_estimate=0,
        recent_token_estimate=0,
        last_message_id=None,
    )

    if should_compact_context(runtime, context_obj):
        context_obj = await compact_conversation_context(
            runtime,
            conversation_id=conversation_id,
            context=context_obj,
        )
        context = {
            "recent_history": context_obj.recent_history,
            "memory_text": context_obj.memory_text,
        }
    else:
        context = {
            "recent_history": context.get("recent_history") or [],
            "memory_text": context.get("memory_text") or "",
        }

    return {
        "context": context,
        "memory_text": context["memory_text"],
        "recent_history": context["recent_history"],
        "current_step": "memory_compacted",
        "_status": "正在压缩上下文...",
    }


async def append_user_message(state: QAState) -> dict[str, Any]:
    runtime = state["runtime"]
    conversation_id = state["conversation_id"]
    query = state["query"]
    policy = _execution_policy(state)

    if not policy["persist_messages"] or conversation_id is None:
        return {
            "user_message": None,
            "current_step": "user_message_appended",
            "_status": "正在理解问题...",
            "messages": [HumanMessage(content=query)],
        }

    user_message = await append_chat_message_dual_write(
        runtime,
        conversation_id,
        "user",
        query,
    )
    await refresh_context_stats_after_message(
        runtime, conversation_id=conversation_id, message=user_message
    )

    return {
        "user_message": user_message,
        "current_step": "user_message_appended",
        "_status": "正在理解问题...",
        "messages": [HumanMessage(content=query)],
    }


async def plan_query_route(state: QAState) -> dict[str, Any]:
    started = perf_counter()
    runtime = state["runtime"]
    query = state["query"]
    logger.info("[QA] Planning route for query: %s", query[:80])
    folder_id = state.get("folder_id")
    bvid = state.get("bvid")
    scope_mode = state.get("scope_mode")
    recent_history = state.get("recent_history") or []
    memory_text = state.get("memory_text") or ""
    policy = _execution_policy(state)

    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        writer = None

    status_map = {
        "direct": "正在回答...",
        "kb_qa_chunk": "正在检索回答...",
        "kb_qa_summary": "正在总结回答...",
    }

    if not policy["planner_enabled"] or not should_use_planner(query):
        intent = classify_query_intent(
            query, folder_id=folder_id, bvid=bvid, scope_mode=scope_mode
        )
        if intent["intent"] == "history":
            route = "direct"
            retrieval_strategy = "chunk"
        elif intent["intent"] in ("video_summary", "folder_summary"):
            route = "kb_qa"
            retrieval_strategy = "summary"
        else:
            route = "kb_qa"
            retrieval_strategy = "chunk"
        use_history = True
        query_plan = None
        status_key = "direct" if route == "direct" else f"kb_qa_{retrieval_strategy}"
        status_text = status_map.get(status_key, "正在检索回答...")

        if writer:
            writer({"_status": status_text, "_route_mode": route, "_mode": retrieval_strategy})
    else:
        if writer:
            writer({"_status": "正在规划回答策略..."})

        runtime.qwen.ensure_configured()
        scope_description = await describe_query_scope(
            runtime, folder_id=folder_id, bvid=bvid, scope_mode=scope_mode
        )
        query_plan = await runtime.qwen.plan_query(
            query=query,
            scope_description=scope_description,
            history=recent_history,
            memory_text=memory_text,
        )

        route = query_plan.route
        retrieval_strategy = query_plan.retrieval_strategy
        use_history = query_plan.use_history

        status_key = "direct" if route == "direct" else f"kb_qa_{retrieval_strategy}"
        status_text = status_map.get(status_key, "正在检索回答...")

        if writer:
            writer({"_route_mode": route, "_mode": retrieval_strategy})

    logger.info("[QA] Route: %s, strategy: %s (%.0fms)", route, retrieval_strategy, (perf_counter() - started) * 1000)
    return {
        "query_plan": query_plan,
        "route_mode": route,
        "retrieval_strategy": retrieval_strategy,
        "use_history": use_history,
        "current_step": "route_planned",
        "_status": status_text or "正在检索回答...",
        "_route_mode": route,
        "_mode": retrieval_strategy,
        "timings": _merge_timings(state, plan_ms=(perf_counter() - started) * 1000),
    }


async def resolve_effective_context(state: QAState) -> dict[str, Any]:
    use_history = state.get("use_history", True)
    context = state.get("context") or {}

    effective_history = resolve_effective_history(use_history, context)
    effective_memory_text = resolve_effective_memory_text(use_history, context)

    return {
        "recent_history": effective_history,
        "memory_text": effective_memory_text,
        "current_step": "context_resolved",
    }


async def prepare_data_for_answer(state: QAState) -> dict[str, Any]:
    started = perf_counter()
    runtime = state["runtime"]
    route_mode = state.get("route_mode")
    retrieval_strategy = state.get("retrieval_strategy")
    logger.info("[QA] Preparing data, route=%s, strategy=%s", route_mode, retrieval_strategy)
    scope = state.get("scope") or {}
    query = state["query"]
    policy = _execution_policy(state)

    if route_mode == "direct":
        return {
            "matches": [],
            "documents": None,
            "sources": [],
            "use_summaries": False,
            "current_step": "data_prepared",
            "_status": "仅使用会话上下文回答...",
            "timings": _merge_timings(state, retrieve_ms=(perf_counter() - started) * 1000),
        }

    if retrieval_strategy == "summary":
        documents = await load_summary_documents(
            runtime,
            folder_id=scope["folder_id"] if scope["scope"] == "folder" else None,
            bvid=scope["bvid"] if scope["scope"] == "video" else None,
        )

        if should_reduce_summary_documents(documents):
            groups = pack_summary_documents(documents)
            if len(groups) > 1:
                reduced_documents: list[dict[str, Any]] = []
                for index, group in enumerate(groups, start=1):
                    summary_text = await runtime.qwen.reduce_summary_documents(
                        query=query, documents=group
                    )
                    if not str(summary_text or "").strip():
                        continue
                    reduced_documents.append(
                        {
                            "bvid": str(group[0].get("bvid") or ""),
                            "video_title": f"第 {index} 组视频摘要",
                            "up_name": "BiliBrain",
                            "summary_text": str(summary_text).strip(),
                        }
                    )
                documents = reduced_documents or documents

        if not documents:
            return {
                "matches": [],
                "documents": None,
                "sources": [],
                "use_summaries": False,
                "current_step": "data_prepared",
                "_status": "当前范围内没有可用摘要。",
                "timings": _merge_timings(state, retrieve_ms=(perf_counter() - started) * 1000),
            }

        sources = build_summary_sources(documents, limit=20)
        return {
            "documents": documents,
            "matches": [],
            "sources": sources,
            "use_summaries": True,
            "current_step": "data_prepared",
            "_status": "正在整理摘要...",
            "_mode": "summary",
            "timings": _merge_timings(state, retrieve_ms=(perf_counter() - started) * 1000),
        }

    # chunk path (default)
    runtime.embedder.ensure_configured()
    logger.info("[QA] Generating embedding and searching...")
    query_embedding = (await runtime.embedder.embed_texts([query]))[0]
    hits = await runtime.vector_store.ahybrid_search(
        query_embedding=query_embedding,
        query_text=query,
        folder_id=scope["folder_id"] if scope["scope"] == "folder" else None,
        bvid=scope["bvid"] if scope["scope"] == "video" else None,
        limit=policy["retrieval_top_k"],
    )
    filtered_hits = await filter_indexed_hits(runtime, hits)
    logger.info("[QA] Vector search: %d hits -> %d filtered", len(hits), len(filtered_hits))
    matches = rerank_search_hits(
        query=query, hits=filtered_hits, limit=policy["rerank_top_k"]
    )

    if not matches:
        return {
            "matches": [],
            "documents": None,
            "sources": [],
            "use_summaries": False,
            "current_step": "data_prepared",
            "_status": "知识库中未找到相关内容。",
            "timings": _merge_timings(state, retrieve_ms=(perf_counter() - started) * 1000),
        }

    sources = build_sources(matches)
    return {
        "matches": matches,
        "documents": None,
        "sources": sources,
        "use_summaries": False,
        "current_step": "data_prepared",
        "_status": f"检索到 {len(matches)} 个相关片段...",
        "_mode": "chunk",
        "timings": _merge_timings(state, retrieve_ms=(perf_counter() - started) * 1000),
    }


async def final_answer(state: QAState) -> dict[str, Any]:
    started = perf_counter()
    runtime = state["runtime"]
    query = state["query"]
    route_mode = state.get("route_mode")
    logger.info("[QA] Generating answer, route=%s, matches=%d, docs=%s", route_mode, len(state.get("matches") or []), bool(state.get("documents")))
    matches = state.get("matches") or []
    documents = state.get("documents")
    use_summaries = state.get("use_summaries", False)
    recent_history = state.get("recent_history") or []
    memory_text = state.get("memory_text") or ""

    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        writer = None

    citation_buffer = ""

    def _feed_delta(delta: str) -> str | None:
        nonlocal citation_buffer
        pending = citation_buffer + delta
        open_brackets = pending.count("[") - pending.count("]")
        if open_brackets > 0 and pending.rstrip().endswith("["):
            citation_buffer = pending
            return None
        if citation_buffer:
            citation_buffer = ""
            return pending
        return delta

    if route_mode == "direct":
        runtime.qwen.ensure_configured()
        answer_text = ""
        async for delta in runtime.qwen.stream_answer_from_history(
            query,
            recent_history,
            memory_text=memory_text,
        ):
            answer_text += delta
            if writer:
                emit_text = _feed_delta(delta)
                if emit_text:
                    writer({"_answer_token": emit_text})

        answer_text = normalize_answer_citations(answer_text.strip())
        if writer:
            writer({"_answer_normalized": answer_text})

        return {
            "answer_text": answer_text,
            "current_step": "answered",
            "messages": [AIMessage(content=answer_text)],
            "timings": _merge_timings(state, answer_ms=(perf_counter() - started) * 1000),
        }

    if not matches and not documents:
        answer_text = build_empty_answer_message(state.get("scope") or {})
        if writer:
            writer({"_answer_token": answer_text})
            writer({"_answer_normalized": answer_text})
        return {
            "answer_text": answer_text,
            "current_step": "answered",
            "messages": [AIMessage(content=answer_text)],
            "timings": _merge_timings(state, answer_ms=(perf_counter() - started) * 1000),
        }

    runtime.qwen.ensure_configured()
    answer_text = ""
    citation_buffer = ""
    if use_summaries and documents:
        async for delta in runtime.qwen.stream_answer_from_summary_documents(
            query,
            documents,
            recent_history,
            memory_text=memory_text,
        ):
            answer_text += delta
            if writer:
                pending = citation_buffer + delta
                open_brackets = pending.count("[") - pending.count("]")
                if open_brackets > 0 and pending.rstrip().endswith("["):
                    citation_buffer = pending
                else:
                    citation_buffer = ""
                    writer({"_answer_token": pending})
    else:
        async for delta in runtime.qwen.stream_answer(
            query,
            matches,
            recent_history,
            memory_text=memory_text,
        ):
            answer_text += delta
            if writer:
                pending = citation_buffer + delta
                open_brackets = pending.count("[") - pending.count("]")
                if open_brackets > 0 and pending.rstrip().endswith("["):
                    citation_buffer = pending
                else:
                    citation_buffer = ""
                    writer({"_answer_token": pending})

    answer_text = normalize_answer_citations(answer_text.strip())
    logger.info("[QA] Answer generated: %d chars (%.0fms)", len(answer_text), (perf_counter() - started) * 1000)
    if writer:
        writer({"_answer_normalized": answer_text})

    return {
        "answer_text": answer_text,
        "current_step": "answered",
        "messages": [AIMessage(content=answer_text)],
        "timings": _merge_timings(state, answer_ms=(perf_counter() - started) * 1000),
    }


async def append_assistant_message(state: QAState) -> dict[str, Any]:
    runtime = state["runtime"]
    conversation_id = state["conversation_id"]
    answer_text = state.get("answer_text") or ""
    sources = state.get("sources") or []
    route_mode = state.get("route_mode") or "kb_qa"
    policy = _execution_policy(state)

    answer_mode = "chunk"
    if sources and len(sources) > 0:
        first_source = sources[0]
        answer_mode = (
            "summary" if first_source.get("source_kind") == "summary" else "chunk"
        )

    if not answer_text or not policy["persist_messages"] or conversation_id is None:
        return {"assistant_message": None}

    assistant_message = await append_chat_message_dual_write(
        runtime,
        conversation_id,
        "assistant",
        answer_text,
        sources=sources,
        answer_mode=answer_mode,
        route_mode=route_mode,
    )
    await refresh_context_stats_after_message(
        runtime,
        conversation_id=conversation_id,
        message=assistant_message,
    )

    return {
        "assistant_message": assistant_message,
        "current_step": "assistant_message_appended",
    }
