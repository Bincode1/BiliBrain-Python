from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from bilibrain.api.deps import get_runtime
from bilibrain.core.runtime import Runtime
from bilibrain.schemas.requests import AgentResumeRequest, AskRequest, ChatConversationCreateRequest, ChatConversationRenameRequest
from bilibrain.services.chat_service import (
    create_chat_conversation,
    delete_chat_conversation,
    get_chat_history,
    list_chat_conversations,
    rename_chat_conversation,
)
from bilibrain.services.unified_agent import (
    answer_with_unified_agent,
    resume_unified_agent_turn,
    stream_resume_unified_agent_events,
    stream_unified_agent_events,
)


router = APIRouter()


@router.get("/api/chat/history")
async def chat_history(
    conversation_id: int | None = Query(default=None, gt=0),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await get_chat_history(runtime, conversation_id)


@router.get("/api/chat/conversations")
async def chat_conversations(runtime: Runtime = Depends(get_runtime)) -> dict[str, object]:
    return await list_chat_conversations(runtime)


@router.post("/api/chat/conversations")
async def chat_conversations_create(
    payload: ChatConversationCreateRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await create_chat_conversation(runtime, payload.title)


@router.delete("/api/chat/conversations/{conversation_id}")
async def chat_conversations_delete(
    conversation_id: int,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await delete_chat_conversation(runtime, conversation_id)


@router.patch("/api/chat/conversations/{conversation_id}")
async def chat_conversations_rename(
    conversation_id: int,
    payload: ChatConversationRenameRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await rename_chat_conversation(runtime, conversation_id, payload.title)


@router.post("/api/ask")
async def ask(payload: AskRequest, runtime: Runtime = Depends(get_runtime)) -> dict[str, object]:
    return await answer_with_unified_agent(
        runtime,
        query=payload.query,
        folder_id=payload.folder_id,
        bvid=payload.bvid,
        scope_mode=payload.scope_mode,
        conversation_id=payload.conversation_id,
        approval_mode=payload.approval_mode,
        actor=payload.actor,
    )


@router.post("/api/ask/stream")
async def ask_stream(payload: AskRequest, runtime: Runtime = Depends(get_runtime)) -> StreamingResponse:
    return StreamingResponse(
        stream_unified_agent_events(
            runtime,
            query=payload.query,
            folder_id=payload.folder_id,
            bvid=payload.bvid,
            scope_mode=payload.scope_mode,
            conversation_id=payload.conversation_id,
            approval_mode=payload.approval_mode,
            actor=payload.actor,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/agent/resume")
async def agent_resume(
    payload: AgentResumeRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await resume_unified_agent_turn(
        runtime,
        session_id=payload.session_id,
        decision=payload.decision,
        conversation_id=payload.conversation_id,
        task_id=payload.task_id,
        folder_id=payload.folder_id,
        bvid=payload.bvid,
        scope_mode=payload.scope_mode,
        actor=payload.actor,
    )


@router.post("/api/agent/resume/stream")
async def agent_resume_stream(
    payload: AgentResumeRequest,
    runtime: Runtime = Depends(get_runtime),
) -> StreamingResponse:
    return StreamingResponse(
        stream_resume_unified_agent_events(
            runtime,
            session_id=payload.session_id,
            decision=payload.decision,
            conversation_id=payload.conversation_id,
            task_id=payload.task_id,
            folder_id=payload.folder_id,
            bvid=payload.bvid,
            scope_mode=payload.scope_mode,
            actor=payload.actor,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
