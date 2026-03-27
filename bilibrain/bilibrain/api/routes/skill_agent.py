from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from bilibrain.api.deps import get_runtime
from bilibrain.core.runtime import Runtime
from bilibrain.schemas.requests import SkillAgentAskRequest, SkillAgentResumeRequest
from bilibrain.services.skill_agent import (
    answer_with_skill_agent,
    resume_skill_agent_turn,
    stream_answer_with_skill_agent_events,
    stream_resume_skill_agent_turn_events,
)


router = APIRouter()


@router.post("/api/skill-agent/ask")
async def skill_agent_ask(
    payload: SkillAgentAskRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await answer_with_skill_agent(
        runtime,
        query=payload.query,
        conversation_id=payload.conversation_id,
        session_id=payload.session_id,
        approval_mode=payload.approval_mode,
        actor=payload.actor,
    )


@router.post("/api/skill-agent/resume")
async def skill_agent_resume(
    payload: SkillAgentResumeRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, object]:
    return await resume_skill_agent_turn(
        runtime,
        session_id=payload.session_id,
        decision=payload.decision,
        conversation_id=payload.conversation_id,
        actor=payload.actor,
    )


@router.post("/api/skill-agent/ask/stream")
async def skill_agent_ask_stream(
    payload: SkillAgentAskRequest,
    runtime: Runtime = Depends(get_runtime),
) -> StreamingResponse:
    return StreamingResponse(
        stream_answer_with_skill_agent_events(
            runtime,
            query=payload.query,
            conversation_id=payload.conversation_id,
            session_id=payload.session_id,
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


@router.post("/api/skill-agent/resume/stream")
async def skill_agent_resume_stream(
    payload: SkillAgentResumeRequest,
    runtime: Runtime = Depends(get_runtime),
) -> StreamingResponse:
    return StreamingResponse(
        stream_resume_skill_agent_turn_events(
            runtime,
            session_id=payload.session_id,
            decision=payload.decision,
            conversation_id=payload.conversation_id,
            actor=payload.actor,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
