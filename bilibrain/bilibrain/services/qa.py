from __future__ import annotations

from typing import Any, AsyncIterator

from bilibrain.core.runtime import Runtime


async def answer_question(
    runtime: Runtime,
    query: str,
    folder_id: int | None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
    deep_research: bool = False,
) -> dict[str, Any]:
    if deep_research:
        from bilibrain.graphs.research import run_research_graph

        return await run_research_graph(
            runtime=runtime,
            query=query,
            folder_id=folder_id,
            bvid=bvid,
            scope_mode=scope_mode,
            conversation_id=conversation_id,
            streaming=False,
        )

    from bilibrain.graphs.qa import run_qa_graph

    return await run_qa_graph(
        runtime=runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        conversation_id=conversation_id,
        streaming=False,
    )


async def stream_answer_events(
    runtime: Runtime,
    query: str,
    folder_id: int | None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
    deep_research: bool = False,
) -> AsyncIterator[str]:
    if deep_research:
        from bilibrain.graphs.research import run_research_graph_stream

        async for event in run_research_graph_stream(
            runtime=runtime,
            query=query,
            folder_id=folder_id,
            bvid=bvid,
            scope_mode=scope_mode,
            conversation_id=conversation_id,
        ):
            yield event
        return

    from bilibrain.graphs.qa import run_qa_graph_stream

    async for event in run_qa_graph_stream(
        runtime=runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        conversation_id=conversation_id,
    ):
        yield event


async def create_chat_conversation(
    runtime: Runtime,
    title: str | None = None,
) -> dict[str, Any]:
    conversation = runtime.db.create_chat_conversation(None, title=title)
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
    conversation_id: int | None = None,
) -> dict[str, Any]:
    if conversation_id is None:
        conversation = runtime.db.get_latest_chat_conversation(None, all_scopes=True)
        if not conversation:
            return {
                "conversation_id": None,
                "folder_id": None,
                "title": "",
                "messages": [],
            }
    else:
        conversation = runtime.db.get_chat_conversation(int(conversation_id))
        if not conversation:
            raise RuntimeError("对话会话不存在，请刷新页面后重试。")

    messages = runtime.db.list_chat_messages(conversation["conversation_id"])
    return {
        "conversation_id": conversation["conversation_id"],
        "folder_id": conversation.get("folder_id"),
        "title": conversation.get("title") or "",
        "messages": messages,
    }


async def list_chat_conversations(runtime: Runtime) -> dict[str, Any]:
    conversations = runtime.db.list_chat_conversations(None, all_scopes=True)
    latest = conversations[0]["conversation_id"] if conversations else None
    return {
        "folder_id": None,
        "active_conversation_id": latest,
        "conversations": conversations,
    }
