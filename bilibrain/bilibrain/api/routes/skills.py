from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from bilibrain.api.deps import get_runtime
from bilibrain.core.runtime import Runtime
from bilibrain.skills.contracts import SkillActivateRequest, SkillCreateRequest


router = APIRouter()


@router.get("/api/skills")
async def list_skills(
    reload: bool = Query(default=False),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    return {
        "enabled": bool(runtime.skill_service and runtime.skill_service.enabled),
        "skills": runtime.skill_service.list_skills(reload=reload) if runtime.skill_service else [],
        "active_skills": runtime.skill_service.get_active_skills() if runtime.skill_service else [],
    }


@router.get("/api/skills/{name}")
async def get_skill(
    name: str,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    if runtime.skill_service is None:
        raise RuntimeError("Skill service is not available.")
    return runtime.skill_service.get_skill(name=name)


@router.post("/api/skills/create")
async def create_skill(
    payload: SkillCreateRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    if runtime.skill_service is None:
        raise RuntimeError("Skill service is not available.")
    skill = runtime.skill_service.create_skill(
        name=payload.name,
        description=payload.description,
        body=payload.body,
    )
    return skill.model_dump()


@router.post("/api/skills/activate")
async def activate_skill(
    payload: SkillActivateRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    if runtime.skill_service is None:
        raise RuntimeError("Skill service is not available.")
    activation = await runtime.skill_service.activate_skill(
        name=payload.name,
        session_id=payload.session_id,
        actor=payload.actor,
    )
    return activation.model_dump()


@router.post("/api/skills/deactivate")
async def deactivate_skill(
    payload: SkillActivateRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    if runtime.skill_service is None:
        raise RuntimeError("Skill service is not available.")
    deactivation = await runtime.skill_service.deactivate_skill(
        name=payload.name,
        session_id=payload.session_id,
        actor=payload.actor,
    )
    return deactivation.model_dump()
