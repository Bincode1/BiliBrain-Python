from __future__ import annotations

from typing import Any, Callable

from langchain_core.tools import tool

from bilibrain.skills.errors import SkillApprovalRequiredError, SkillError


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
    @tool(
        "skill",
        description=(
            "Load the full instructions for an already activated skill by name. "
            "Use this only when the current task clearly matches one of the available skills."
        ),
    )
    async def skill(name: str) -> dict[str, Any]:
        summary = {"name": name}
        _emit(
            event_callback,
            "skill",
            {
                "phase": "start",
                "name": name,
                "session_id": session_id,
                "summary": summary,
            },
        )
        try:
            payload = skill_service.read_skill(name=name, session_id=session_id, actor=actor)
        except Exception as exc:
            phase = "approval_required" if isinstance(exc, SkillApprovalRequiredError) else "blocked" if isinstance(exc, SkillError) else "error"
            _emit(
                event_callback,
                "skill",
                {
                    "phase": phase,
                    "name": name,
                    "session_id": session_id,
                    "error": str(exc),
                },
            )
            raise

        _emit(
            event_callback,
            "skill",
            {
                "phase": "loaded",
                "name": payload["name"],
                "session_id": session_id,
                "skill_root": payload.get("directory_path"),
                "resource_count": len(payload.get("resources") or []),
            },
        )
        _emit(
            event_callback,
            "skills",
            {
                "active_skills": skill_service.get_active_skills(session_id),
            },
        )
        return {
            "name": payload["name"],
            "description": payload["description"],
            "content": payload["body"],
            "skill_root": payload["directory_path"],
            "skill_path": payload["skill_path"],
            "variables": payload.get("variables") or {},
            "resources": payload.get("resources") or [],
            "resource_map": payload.get("resource_map") or {},
            "allowed_tools": payload.get("allowed_tools") or [],
            "usage_rules": payload.get("usage_rules") or [],
        }

    return [skill]
