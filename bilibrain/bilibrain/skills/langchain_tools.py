from __future__ import annotations

from typing import Any, Callable

from langchain_core.tools import tool


def _emit(callback: Callable[[str, dict[str, Any]], None] | None, event_type: str, payload: dict[str, Any]) -> None:
    if callback is None:
        return
    callback(event_type, payload)


def build_skill_langchain_tools(
    skill_service,
    *,
    session_id: str,
    actor: str = "agent",
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
):
    @tool("activate_skill", description="Activate a named skill from the available skills catalog before using a specialized workflow.")
    async def activate_skill(name: str) -> dict:
        _emit(
            event_callback,
            "skill",
            {
                "phase": "start",
                "name": name,
                "message": f"正在激活 skill: {name}",
            },
        )
        activation = skill_service.activate_skill(
            name=name,
            session_id=session_id,
            actor=actor,
        )
        payload = activation.model_dump()
        skill = payload.get("skill") or {}
        _emit(
            event_callback,
            "skill",
            {
                "phase": "activated",
                "name": str(skill.get("name") or name),
                "source": str(skill.get("source") or ""),
                "message": f"已激活 skill: {skill.get('name') or name}",
            },
        )
        _emit(
            event_callback,
            "skills",
            {
                "active_skills": skill_service.get_active_skills(session_id),
            },
        )
        return payload

    @tool("list_active_skills", description="List skills that are currently active for this session.")
    async def list_active_skills() -> dict:
        payload = {
            "session_id": session_id,
            "active_skills": skill_service.get_active_skills(session_id),
        }
        _emit(
            event_callback,
            "skills",
            {
                "active_skills": payload["active_skills"],
            },
        )
        return payload

    return [activate_skill, list_active_skills]
