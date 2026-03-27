from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from bilibrain.api.deps import get_runtime
from bilibrain.core.runtime import Runtime
from bilibrain.skills.contracts import SkillActivateRequest


router = APIRouter()


@router.get("/api/skills")
async def list_skills(
    session_id: str | None = Query(default=None),
    reload: bool = Query(default=False),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    return {
        "enabled": bool(runtime.skill_service and runtime.skill_service.enabled),
        "skills": runtime.skill_service.list_skills(session_id=session_id, reload=reload) if runtime.skill_service else [],
        "active_skills": runtime.skill_service.get_active_skills(session_id) if runtime.skill_service and session_id else [],
    }


@router.post("/api/skills/activate")
async def activate_skill(
    payload: SkillActivateRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    if runtime.skill_service is None:
        raise RuntimeError("Skill service is not available.")
    activation = runtime.skill_service.activate_skill(
        name=payload.name,
        session_id=payload.session_id,
        actor=payload.actor,
    )
    return activation.model_dump()


@router.get("/api/skills/sessions/{session_id}")
async def get_active_skills(session_id: str, runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    if runtime.skill_service is None:
        raise RuntimeError("Skill service is not available.")
    return {
        "session_id": session_id,
        "active_skills": runtime.skill_service.get_active_skills(session_id),
        "available_skills_prompt": runtime.skill_service.build_available_skills_prompt(session_id=session_id),
    }
