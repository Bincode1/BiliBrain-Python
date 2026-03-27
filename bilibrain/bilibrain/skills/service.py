from __future__ import annotations

from pathlib import Path
from typing import Any

from bilibrain.skills.contracts import (
    SkillActivation,
    SkillDescriptor,
    SkillManifest,
    SkillSource,
    SkillSourceConfig,
)
from bilibrain.skills.errors import SkillNotFoundError, SkillPolicyError
from bilibrain.skills.registry import SkillRegistry


class SkillService:
    def __init__(
        self,
        *,
        registry: SkillRegistry,
        enabled: bool = True,
        allow_repo_skills: bool = False,
    ) -> None:
        self.registry = registry
        self.enabled = bool(enabled)
        self.allow_repo_skills = bool(allow_repo_skills)
        self._active_sessions: dict[str, list[str]] = {}

    def list_skills(self, *, session_id: str | None = None, reload: bool = False) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        if reload:
            self.registry.reload()
        active_names = set(self._active_sessions.get(session_id or "", []))
        result: list[dict[str, Any]] = []
        for item in self.registry.list_skills():
            descriptor = item.model_copy(update={"active": item.name in active_names})
            result.append(descriptor.model_dump())
        return result

    def get_active_skills(self, session_id: str) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        active_names = self._active_sessions.get(session_id, [])
        result: list[dict[str, Any]] = []
        for name in active_names:
            skill = self.registry.get_skill(name)
            if skill is None:
                continue
            result.append(skill.model_dump())
        return result

    def activate_skill(self, *, name: str, session_id: str, actor: str = "system") -> SkillActivation:
        if not self.enabled:
            raise RuntimeError("Skills are disabled.")
        skill = self.registry.get_skill(name)
        if skill is None:
            raise SkillNotFoundError(f"Unknown skill: {name}")
        if skill.source == SkillSource.REPO and not self.allow_repo_skills:
            raise SkillPolicyError("Repo skills are disabled until the workspace is trusted.")

        active = self._active_sessions.setdefault(session_id, [])
        if name not in active:
            active.append(name)
        return SkillActivation(session_id=session_id, skill=skill, actor=actor)

    def build_available_skills_prompt(self, *, session_id: str | None = None) -> str:
        skills = self.list_skills(session_id=session_id)
        if not skills:
            return "<available_skills />"
        lines = ["<available_skills>"]
        for item in skills:
            lines.append("  <skill>")
            lines.append(f"    <name>{item['name']}</name>")
            lines.append(f"    <description>{item['description']}</description>")
            lines.append(f"    <source>{item['source']}</source>")
            lines.append(f"    <allow_model_invocation>{str(bool(item['allow_model_invocation'])).lower()}</allow_model_invocation>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def build_active_skills_prompt(self, *, session_id: str) -> str:
        skills = self.get_active_skills(session_id)
        if not skills:
            return "<active_skills />"
        lines = ["<active_skills>"]
        for item in skills:
            lines.append(f"  <skill name=\"{item['name']}\" source=\"{item['source']}\">")
            lines.append("    <instructions>")
            for body_line in str(item.get("body") or "").splitlines():
                lines.append(f"      {body_line}")
            lines.append("    </instructions>")
            lines.append("  </skill>")
        lines.append("</active_skills>")
        return "\n".join(lines)


def create_skill_service(settings) -> SkillService:
    source_configs = [
        SkillSourceConfig(
            source=SkillSource.SYSTEM,
            root=settings.skills_builtin_root,
            precedence=0,
            enabled=True,
            trusted=True,
        ),
        SkillSourceConfig(
            source=SkillSource.USER,
            root=settings.skills_user_root,
            precedence=10,
            enabled=bool(settings.skills_user_enabled),
            trusted=True,
        ),
        SkillSourceConfig(
            source=SkillSource.REPO,
            root=settings.skills_repo_root,
            precedence=20,
            enabled=bool(settings.skills_repo_enabled),
            trusted=bool(settings.skills_trust_repo),
        ),
    ]
    registry = SkillRegistry(source_configs=source_configs)
    registry.reload()
    return SkillService(
        registry=registry,
        enabled=bool(settings.skills_enabled),
        allow_repo_skills=bool(settings.skills_trust_repo),
    )
