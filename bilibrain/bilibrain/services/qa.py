from __future__ import annotations

import json
from typing import Any, AsyncIterator

from bilibrain.core.runtime import Runtime
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
) -> dict[str, Any] | None:
    routing = classify_query_intent(query, folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    if routing["intent"] == "detail_qa":
        return None

    documents = await load_summary_documents(
        runtime,
        folder_id=folder_id if routing["scope"] == "folder" else None,
        bvid=bvid if routing["scope"] == "video" else None,
    )
    if not documents:
        return None

    answer_documents = await _reduce_summary_documents(runtime, query, documents)
    answer = await runtime.qwen.answer_from_summary_documents(query, answer_documents, history)
    return {
        "answer": answer,
        "sources": build_summary_sources(documents, limit=20),
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
    history = load_chat_history(runtime, conversation["conversation_id"])
    runtime.db.append_chat_message(conversation["conversation_id"], "user", query)
    routing = classify_query_intent(query, folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)

    try:
        summary_payload = await build_summary_answer(runtime, query, folder_id, bvid, scope_mode, history)
    except Exception:
        summary_payload = None
    if summary_payload:
        runtime.db.append_chat_message(
            conversation["conversation_id"],
            "assistant",
            summary_payload["answer"],
            sources=summary_payload["sources"],
            answer_mode="summary",
        )
        return {
            "conversation_id": conversation["conversation_id"],
            "answer": summary_payload["answer"],
            "sources": summary_payload["sources"],
            "answer_mode": "summary",
        }

    matches = await search_matches(
        runtime,
        query,
        folder_id if routing["scope"] == "folder" else None,
        bvid=bvid if routing["scope"] == "video" else None,
    )
    if not matches:
        runtime.db.append_chat_message(
            conversation["conversation_id"],
            "assistant",
            ASK_EMPTY_MESSAGE,
            sources=[],
            answer_mode="chunk",
        )
        return {
            "conversation_id": conversation["conversation_id"],
            "answer": ASK_EMPTY_MESSAGE,
            "sources": [],
            "answer_mode": "chunk",
        }

    sources = build_sources(matches)
    answer = await runtime.qwen.answer(query, matches, history)
    runtime.db.append_chat_message(
        conversation["conversation_id"],
        "assistant",
        answer,
        sources=sources,
        answer_mode="chunk",
    )
    return {
        "conversation_id": conversation["conversation_id"],
        "answer": answer,
        "sources": sources,
        "answer_mode": "chunk",
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
    history = load_chat_history(runtime, conversation["conversation_id"])
    runtime.db.append_chat_message(conversation["conversation_id"], "user", query)
    yield sse_event("conversation", {"conversation_id": conversation["conversation_id"]})

    routing = classify_query_intent(query, folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    if routing["intent"] != "detail_qa":
        yield sse_event("mode", {"mode": "summary"})
        yield sse_event("status", {"delta": "正在整理摘要..."})
        try:
            documents = await load_summary_documents(
                runtime,
                folder_id=folder_id if routing["scope"] == "folder" else None,
                bvid=bvid if routing["scope"] == "video" else None,
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
                async for delta in runtime.qwen.stream_answer_from_summary_documents(query, answer_documents, history):
                    answer_fragments.append(delta)
                    yield sse_event("answer", {"delta": delta})
                answer_text = "".join(answer_fragments).strip()
                if answer_text:
                    runtime.db.append_chat_message(
                        conversation["conversation_id"],
                        "assistant",
                        answer_text,
                        sources=sources,
                        answer_mode="summary",
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
        folder_id if routing["scope"] == "folder" else None,
        bvid=bvid if routing["scope"] == "video" else None,
    )
    if not matches:
        runtime.db.append_chat_message(
            conversation["conversation_id"],
            "assistant",
            STREAM_EMPTY_MESSAGE,
            sources=[],
            answer_mode="chunk",
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
        async for delta in runtime.qwen.stream_answer(query, matches, history):
            answer_fragments.append(delta)
            yield sse_event("answer", {"delta": delta})
        answer_text = "".join(answer_fragments).strip()
        if answer_text:
            runtime.db.append_chat_message(
                conversation["conversation_id"],
                "assistant",
                answer_text,
                sources=sources,
                answer_mode="chunk",
            )
        yield sse_event("done")
    except Exception as exc:
        answer_text = "".join(answer_fragments).strip()
        if answer_text:
            runtime.db.append_chat_message(
                conversation["conversation_id"],
                "assistant",
                answer_text,
                sources=sources,
                answer_mode="chunk",
            )
        yield sse_event("error", {"detail": str(exc)})
