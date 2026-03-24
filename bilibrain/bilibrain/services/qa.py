from __future__ import annotations

import json
from typing import Any, AsyncIterator

from bilibrain.core.runtime import Runtime
from bilibrain.services.chat_memory import (
    build_conversation_context,
    compact_conversation_context,
    refresh_context_stats_after_message,
    should_compact_context,
)
from bilibrain.services.common import (
    build_jump_url,
    rerank_search_hits,
    seconds_to_timestamp,
)
from bilibrain.services.summary import (
    build_summary_sources,
    classify_query_intent,
    load_summary_documents,
    pack_summary_documents,
    resolve_query_scope,
)


ASK_EMPTY_MESSAGE = "当前没有可检索的视频内容。请先在左侧选择视频并完成处理。"
STREAM_EMPTY_MESSAGE = "当前没有可检索的视频内容。请先完成至少一个视频的处理。"
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


def sse_event(event: str, data: dict[str, Any] | None = None) -> str:
    payload = json.dumps(data or {}, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def filter_indexed_hits(runtime: Runtime, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    statuses = runtime.db.get_pipeline_overall_statuses([str(hit.get("bvid") or "") for hit in hits])
    filtered: list[dict[str, Any]] = []
    for hit in hits:
        if statuses.get(str(hit["bvid"]), "pending") == "indexed":
            filtered.append(hit)
    return filtered


async def search_matches(
    runtime: Runtime,
    query: str,
    folder_id: int | None,
    *,
    bvid: str | None = None,
    search_limit: int = 40,
    match_limit: int = 10,
) -> list[dict[str, Any]]:
    runtime.embedder.ensure_configured()
    query_embedding = (await runtime.embedder.embed_texts([query]))[0]
    hits = runtime.vector_store.hybrid_search(
        query_embedding=query_embedding,
        query_text=query,
        folder_id=folder_id,
        bvid=bvid,
        limit=search_limit,
    )
    return rerank_search_hits(
        query=query,
        hits=filter_indexed_hits(runtime, hits),
        limit=match_limit,
    )


def _summary_total_chars(documents: list[dict[str, Any]]) -> int:
    return sum(len(str(item.get("summary_text") or "")) for item in documents)


async def _reduce_summary_documents(
    runtime: Runtime,
    query: str,
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(documents) <= SUMMARY_REDUCE_DOC_THRESHOLD and _summary_total_chars(documents) <= SUMMARY_REDUCE_CHAR_THRESHOLD:
        return documents

    groups = pack_summary_documents(documents)
    if len(groups) <= 1:
        return documents

    reduced_documents: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        summary_text = await runtime.qwen.reduce_summary_documents(query=query, documents=group)
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
    return reduced_documents or documents


def build_sources(matches: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for index, item in enumerate(matches, start=1):
        sources.append(
            {
                "ref_index": index,
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


def resolve_chat_conversation(
    runtime: Runtime,
    folder_id: int | None,
    conversation_id: int | None = None,
) -> dict[str, Any]:
    normalized_folder_id = int(folder_id) if folder_id else None
    if conversation_id is None:
        return runtime.db.create_chat_conversation(normalized_folder_id)

    conversation = runtime.db.get_chat_conversation(int(conversation_id))
    if not conversation:
        raise RuntimeError("对话会话不存在，请刷新页面后重试。")
    return conversation


def load_chat_history(runtime: Runtime, conversation_id: int) -> list[dict[str, Any]]:
    return runtime.db.list_chat_messages(conversation_id)


def should_use_planner(query: str) -> bool:
    payload = " ".join(str(query or "").lower().split())
    if not payload:
        return False
    return any(keyword in payload for keyword in PLANNER_HINT_KEYWORDS)


async def list_chat_conversations(runtime: Runtime, folder_id: int | None) -> dict[str, Any]:
    conversations = runtime.db.list_chat_conversations(None, all_scopes=True)
    latest = conversations[0]["conversation_id"] if conversations else None
    return {
        "folder_id": None,
        "active_conversation_id": latest,
        "conversations": conversations,
    }


async def create_chat_conversation(
    runtime: Runtime,
    folder_id: int | None,
    title: str | None = None,
) -> dict[str, Any]:
    normalized_folder_id = int(folder_id) if folder_id else None
    conversation = runtime.db.create_chat_conversation(normalized_folder_id, title=title)
    return {
        "conversation": conversation,
        "messages": [],
    }


async def delete_chat_conversation(runtime: Runtime, conversation_id: int) -> dict[str, Any]:
    conversation = runtime.db.get_chat_conversation(int(conversation_id))
    if not conversation:
        raise RuntimeError("对话会话不存在，请刷新页面后重试。")

    runtime.db.delete_chat_conversation(int(conversation_id))
    conversations = runtime.db.list_chat_conversations(None, all_scopes=True)
    next_active_id = conversations[0]["conversation_id"] if conversations else None
    return {
        "deleted_conversation_id": int(conversation_id),
        "active_conversation_id": next_active_id,
        "conversations": conversations,
    }


async def rename_chat_conversation(
    runtime: Runtime,
    conversation_id: int,
    title: str,
) -> dict[str, Any]:
    conversation = runtime.db.rename_chat_conversation(int(conversation_id), title)
    if not conversation:
        raise RuntimeError("对话会话不存在，请刷新页面后重试。")
    conversations = runtime.db.list_chat_conversations(None, all_scopes=True)
    return {
        "conversation": conversation,
        "conversations": conversations,
    }


async def get_chat_history(
    runtime: Runtime,
    folder_id: int | None,
    conversation_id: int | None = None,
) -> dict[str, Any]:
    normalized_folder_id = int(folder_id) if folder_id else None
    if conversation_id is None:
        conversation = runtime.db.get_latest_chat_conversation(None, all_scopes=True)
        if not conversation:
            return {
                "conversation_id": None,
                "folder_id": normalized_folder_id,
                "title": "",
                "messages": [],
            }
    else:
        conversation = resolve_chat_conversation(runtime, folder_id, conversation_id)
    messages = load_chat_history(runtime, conversation["conversation_id"])
    return {
        "conversation_id": conversation["conversation_id"],
        "folder_id": conversation.get("folder_id"),
        "title": conversation.get("title") or "",
        "messages": messages,
    }


async def build_summary_answer(
    runtime: Runtime,
    query: str,
    folder_id: int | None,
    bvid: str | None,
    scope_mode: str | None,
    history: list[dict[str, Any]],
    memory_text: str = "",
) -> dict[str, Any] | None:
    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)

    documents = await load_summary_documents(
        runtime,
        folder_id=scope["folder_id"] if scope["scope"] == "folder" else None,
        bvid=scope["bvid"] if scope["scope"] == "video" else None,
    )
    if not documents:
        return None

    answer_documents = await _reduce_summary_documents(runtime, query, documents)
    answer = await runtime.qwen.answer_from_summary_documents(
        query,
        answer_documents,
        history,
        memory_text=memory_text,
    )
    return {
        "answer": answer,
        "sources": build_summary_sources(documents, limit=20),
    }


def describe_query_scope(
    runtime: Runtime,
    *,
    folder_id: int | None,
    bvid: str | None,
    scope_mode: str | None,
) -> str:
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


async def resolve_query_plan(
    runtime: Runtime,
    *,
    query: str,
    folder_id: int | None,
    bvid: str | None,
    scope_mode: str | None,
    history: list[dict[str, Any]],
    memory_text: str = "",
) -> dict[str, Any]:
    if not should_use_planner(query):
        intent = classify_query_intent(query, folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
        route = "summary_only" if intent["intent"] != "detail_qa" else "chunk_only"
        return {
            "route": route,
            "use_history": True,
            "use_current_scope": True,
            "retrieval_mode": "summary" if route == "summary_only" else "chunk",
            "reason": "命中直接规则，跳过 LLM planner。",
        }

    scope_description = describe_query_scope(
        runtime,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
    )
    plan = await runtime.qwen.plan_query(
        query=query,
        scope_description=scope_description,
        history=history,
        memory_text=memory_text,
    )
    route = plan.route
    retrieval_mode = plan.retrieval_mode
    if route == "history_only":
        retrieval_mode = "none"
    elif route == "summary_only":
        retrieval_mode = "summary"
    elif route == "chunk_only":
        retrieval_mode = "chunk"
    elif route == "mixed" and retrieval_mode == "none":
        retrieval_mode = "chunk"
    return {
        "route": route,
        "use_history": bool(plan.use_history),
        "use_current_scope": bool(plan.use_current_scope),
        "retrieval_mode": retrieval_mode,
        "reason": str(plan.reason or "").strip(),
    }


async def answer_question(
    runtime: Runtime,
    query: str,
    folder_id: int | None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
) -> dict[str, Any]:
    runtime.qwen.ensure_configured()
    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    conversation = resolve_chat_conversation(
        runtime,
        scope["folder_id"] if scope["scope"] == "folder" else None,
        conversation_id,
    )
    context = build_conversation_context(
        runtime,
        conversation_id=conversation["conversation_id"],
    )
    if should_compact_context(runtime, context):
        context = await compact_conversation_context(
            runtime,
            conversation_id=conversation["conversation_id"],
            context=context,
        )
    user_message = runtime.db.append_chat_message(conversation["conversation_id"], "user", query)
    refresh_context_stats_after_message(
        runtime,
        conversation_id=conversation["conversation_id"],
        message=user_message,
    )
    plan = await resolve_query_plan(
        runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        history=context.recent_history,
        memory_text=context.memory_text,
    )
    effective_history = context.recent_history if plan["use_history"] else []
    effective_memory_text = context.memory_text if plan["use_history"] else ""

    if plan["route"] == "history_only":
        answer = await runtime.qwen.answer_from_history(
            query,
            context.recent_history,
            memory_text=context.memory_text,
        )
        assistant_message = runtime.db.append_chat_message(
            conversation["conversation_id"],
            "assistant",
            answer,
            sources=[],
            answer_mode=None,
            route_mode=plan["route"],
        )
        refresh_context_stats_after_message(
            runtime,
            conversation_id=conversation["conversation_id"],
            message=assistant_message,
        )
        return {
            "conversation_id": conversation["conversation_id"],
            "answer": answer,
            "sources": [],
            "answer_mode": None,
            "route_mode": plan["route"],
        }

    if plan["retrieval_mode"] == "summary":
        try:
            summary_payload = await build_summary_answer(
                runtime,
                query,
                folder_id,
                bvid,
                scope_mode,
                effective_history,
                memory_text=effective_memory_text,
            )
        except Exception:
            summary_payload = None
        if summary_payload:
            assistant_message = runtime.db.append_chat_message(
                conversation["conversation_id"],
                "assistant",
                summary_payload["answer"],
                sources=summary_payload["sources"],
                answer_mode="summary",
                route_mode=plan["route"],
            )
            refresh_context_stats_after_message(
                runtime,
                conversation_id=conversation["conversation_id"],
                message=assistant_message,
            )
            return {
                "conversation_id": conversation["conversation_id"],
                "answer": summary_payload["answer"],
                "sources": summary_payload["sources"],
                "answer_mode": "summary",
                "route_mode": plan["route"],
            }

    matches = await search_matches(
        runtime,
        query,
        scope["folder_id"] if scope["scope"] == "folder" else None,
        bvid=scope["bvid"] if scope["scope"] == "video" else None,
    )
    if not matches:
        assistant_message = runtime.db.append_chat_message(
            conversation["conversation_id"],
            "assistant",
            ASK_EMPTY_MESSAGE,
            sources=[],
            answer_mode="chunk",
            route_mode=plan["route"],
        )
        refresh_context_stats_after_message(
            runtime,
            conversation_id=conversation["conversation_id"],
            message=assistant_message,
        )
        return {
            "conversation_id": conversation["conversation_id"],
            "answer": ASK_EMPTY_MESSAGE,
            "sources": [],
            "answer_mode": "chunk",
            "route_mode": plan["route"],
        }

    sources = build_sources(matches)
    answer = await runtime.qwen.answer(query, matches, effective_history, memory_text=effective_memory_text)
    assistant_message = runtime.db.append_chat_message(
        conversation["conversation_id"],
        "assistant",
        answer,
        sources=sources,
        answer_mode="chunk",
        route_mode=plan["route"],
    )
    refresh_context_stats_after_message(
        runtime,
        conversation_id=conversation["conversation_id"],
        message=assistant_message,
    )
    return {
        "conversation_id": conversation["conversation_id"],
        "answer": answer,
        "sources": sources,
        "answer_mode": "chunk",
        "route_mode": plan["route"],
    }


async def stream_answer_events(
    runtime: Runtime,
    query: str,
    folder_id: int | None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
) -> AsyncIterator[str]:
    runtime.qwen.ensure_configured()
    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    conversation = resolve_chat_conversation(
        runtime,
        scope["folder_id"] if scope["scope"] == "folder" else None,
        conversation_id,
    )
    context = build_conversation_context(
        runtime,
        conversation_id=conversation["conversation_id"],
    )
    if should_compact_context(runtime, context):
        yield sse_event("status", {"delta": "正在压缩上下文..."})
        context = await compact_conversation_context(
            runtime,
            conversation_id=conversation["conversation_id"],
            context=context,
        )
    user_message = runtime.db.append_chat_message(conversation["conversation_id"], "user", query)
    refresh_context_stats_after_message(
        runtime,
        conversation_id=conversation["conversation_id"],
        message=user_message,
    )
    yield sse_event("conversation", {"conversation_id": conversation["conversation_id"]})
    yield sse_event("status", {"delta": "正在理解问题..."})
    plan = await resolve_query_plan(
        runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        history=context.recent_history,
        memory_text=context.memory_text,
    )
    effective_history = context.recent_history if plan["use_history"] else []
    effective_memory_text = context.memory_text if plan["use_history"] else ""
    yield sse_event("route", {"route_mode": plan["route"]})

    if plan["route"] == "history_only":
        yield sse_event("status", {"delta": "正在回顾本次会话..."})
        answer_fragments: list[str] = []
        try:
            async for delta in runtime.qwen.stream_answer_from_history(
                query,
                context.recent_history,
                memory_text=context.memory_text,
            ):
                answer_fragments.append(delta)
                yield sse_event("answer", {"delta": delta})
            answer_text = "".join(answer_fragments).strip()
            if answer_text:
                assistant_message = runtime.db.append_chat_message(
                    conversation["conversation_id"],
                    "assistant",
                    answer_text,
                    sources=[],
                    answer_mode=None,
                    route_mode=plan["route"],
                )
                refresh_context_stats_after_message(
                    runtime,
                    conversation_id=conversation["conversation_id"],
                    message=assistant_message,
                )
            yield sse_event("done")
            return
        except Exception as exc:
            yield sse_event("error", {"detail": str(exc)})
            return

    if plan["retrieval_mode"] == "summary":
        yield sse_event("mode", {"mode": "summary"})
        yield sse_event("status", {"delta": "正在整理摘要..."})
        try:
            documents = await load_summary_documents(
                runtime,
                folder_id=scope["folder_id"] if scope["scope"] == "folder" else None,
                bvid=scope["bvid"] if scope["scope"] == "video" else None,
            )
        except Exception:
            documents = []

        if documents:
            answer_documents = await _reduce_summary_documents(runtime, query, documents)
            sources = build_summary_sources(documents, limit=20)
            yield sse_event("sources", {"sources": sources})
            yield sse_event("status", {"delta": "已整理摘要，正在生成答案..."})
            answer_fragments: list[str] = []
            try:
                async for delta in runtime.qwen.stream_answer_from_summary_documents(
                    query,
                    answer_documents,
                    effective_history,
                    memory_text=effective_memory_text,
                ):
                    answer_fragments.append(delta)
                    yield sse_event("answer", {"delta": delta})
                answer_text = "".join(answer_fragments).strip()
                if answer_text:
                    assistant_message = runtime.db.append_chat_message(
                        conversation["conversation_id"],
                        "assistant",
                        answer_text,
                        sources=sources,
                        answer_mode="summary",
                        route_mode=plan["route"],
                    )
                    refresh_context_stats_after_message(
                        runtime,
                        conversation_id=conversation["conversation_id"],
                        message=assistant_message,
                    )
                yield sse_event("done")
                return
            except Exception:
                pass

    yield sse_event("mode", {"mode": "chunk"})
    yield sse_event("status", {"delta": "检索中..."})

    matches = await search_matches(
        runtime,
        query,
        scope["folder_id"] if scope["scope"] == "folder" else None,
        bvid=scope["bvid"] if scope["scope"] == "video" else None,
    )
    if not matches:
        assistant_message = runtime.db.append_chat_message(
            conversation["conversation_id"],
            "assistant",
            STREAM_EMPTY_MESSAGE,
            sources=[],
            answer_mode="chunk",
            route_mode=plan["route"],
        )
        refresh_context_stats_after_message(
            runtime,
            conversation_id=conversation["conversation_id"],
            message=assistant_message,
        )
        yield sse_event("answer", {"delta": STREAM_EMPTY_MESSAGE})
        yield sse_event("sources", {"sources": []})
        yield sse_event("done")
        return

    sources = build_sources(matches)
    yield sse_event("sources", {"sources": sources})
    yield sse_event("status", {"delta": "已检索到资料，正在生成答案..."})
    answer_fragments: list[str] = []
    try:
        async for delta in runtime.qwen.stream_answer(
            query,
            matches,
            effective_history,
            memory_text=effective_memory_text,
        ):
            answer_fragments.append(delta)
            yield sse_event("answer", {"delta": delta})
        answer_text = "".join(answer_fragments).strip()
        if answer_text:
            assistant_message = runtime.db.append_chat_message(
                conversation["conversation_id"],
                "assistant",
                answer_text,
                sources=sources,
                answer_mode="chunk",
                route_mode=plan["route"],
            )
            refresh_context_stats_after_message(
                runtime,
                conversation_id=conversation["conversation_id"],
                message=assistant_message,
            )
        yield sse_event("done")
    except Exception as exc:
        answer_text = "".join(answer_fragments).strip()
        if answer_text:
            assistant_message = runtime.db.append_chat_message(
                conversation["conversation_id"],
                "assistant",
                answer_text,
                sources=sources,
                answer_mode="chunk",
                route_mode=plan["route"],
            )
            refresh_context_stats_after_message(
                runtime,
                conversation_id=conversation["conversation_id"],
                message=assistant_message,
            )
        yield sse_event("error", {"detail": str(exc)})
