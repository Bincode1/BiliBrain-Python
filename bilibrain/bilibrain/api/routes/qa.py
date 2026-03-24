from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from bilibrain.api.deps import get_runtime
from bilibrain.core.runtime import Runtime
from bilibrain.schemas.requests import AskRequest, ChatConversationCreateRequest
from bilibrain.services.qa import (
    answer_question,
    create_chat_conversation,
    delete_chat_conversation,
    get_chat_history,
    list_chat_conversations,
    stream_answer_events,
)


router = APIRouter()


@router.get("/api/chat/history")
async def chat_history(
    folder_id: int | None = Query(default=None, gt=0),
    conversation_id: int | None = Query(default=None, gt=0),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await get_chat_history(runtime, folder_id, conversation_id)


@router.get("/api/chat/conversations")
async def chat_conversations(
    folder_id: int | None = Query(default=None, gt=0),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await list_chat_conversations(runtime, folder_id)


@router.post("/api/chat/conversations")
async def chat_conversations_create(
    payload: ChatConversationCreateRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await create_chat_conversation(runtime, payload.folder_id, payload.title)


@router.delete("/api/chat/conversations/{conversation_id}")
async def chat_conversations_delete(
    conversation_id: int,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await delete_chat_conversation(runtime, conversation_id)


@router.post("/api/ask")
async def ask(payload: AskRequest, runtime: Runtime = Depends(get_runtime)) -> dict[str, object]:
    return await answer_question(
        runtime,
        payload.query,
        payload.folder_id,
        payload.bvid,
        payload.scope_mode,
        payload.conversation_id,
    )


@router.post("/api/ask/stream")
async def ask_stream(payload: AskRequest, runtime: Runtime = Depends(get_runtime)) -> StreamingResponse:
    return StreamingResponse(
        stream_answer_events(
            runtime,
            payload.query,
            payload.folder_id,
            payload.bvid,
            payload.scope_mode,
            payload.conversation_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
