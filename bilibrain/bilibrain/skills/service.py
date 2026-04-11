from __future__ import annotations

from pathlib import Path
from typing import Any

from bilibrain.skills.contracts import (
    SkillActivation,
    SkillDescriptor,
    SkillManifest,
)
from bilibrain.skills.errors import SkillError, SkillNotFoundError
from bilibrain.skills.registry import SkillRegistry


class SkillService:
    def __init__(
        self,
        *,
        registry: SkillRegistry,
        db,
        enabled: bool = True,
    ) -> None:
        self.registry = registry
        self.db = db
        self.enabled = bool(enabled)
        self._active_skills: set[str] = set()
        # 从数据库加载激活的技能将在startup_runtime中异步执行

    async def _load_active_skills(self) -> None:
        """从数据库加载激活的技能"""
        if self.db:
            active_skill_names = await self.db.get_active_skills()
            self._active_skills = set(active_skill_names)

    def list_skills(self, *, reload: bool = False) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        if reload:
            self.registry.reload()
        result: list[dict[str, Any]] = []
        for item in self.registry.list_skills():
            descriptor = item.model_copy(update={"active": item.name in self._active_skills})
            result.append(descriptor.model_dump())
        return result

    def get_active_skills(self, session_id: str | None = None) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        result: list[dict[str, Any]] = []
        for name in self._active_skills:
            skill = self.registry.get_skill(name)
            if skill is None:
                continue
            result.append(skill.model_dump())
        return result

    def get_skill(self, *, name: str) -> dict[str, Any]:
        if not self.enabled:
            raise SkillNotFoundError(f"Unknown skill: {name}")
        skill = self.registry.get_skill(name)
        if skill is None:
            raise SkillNotFoundError(f"Unknown skill: {name}")
        return skill.model_copy(update={"active": name in self._active_skills}).model_dump()

    def create_skill(self, *, name: str, description: str, body: str) -> SkillManifest:
        if not self.enabled:
            raise RuntimeError("Skills are disabled.")

        if self.registry.get_skill(name) is not None:
            raise SkillError(f"Skill '{name}' already exists.")

        skill_dir = self.registry.root / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = skill_dir / "SKILL.md"
        content = f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"
        skill_file.write_text(content, encoding="utf-8")

        self.registry.reload()
        skill = self.registry.get_skill(name)
        if skill is None:
            raise SkillError(f"Failed to load created skill: {name}")
        return skill

    async def activate_skill(self, *, name: str, session_id: str | None = None, actor: str = "system") -> SkillActivation:
        if not self.enabled:
            raise RuntimeError("Skills are disabled.")
        skill = self.registry.get_skill(name)
        if skill is None:
            raise SkillNotFoundError(f"Unknown skill: {name}")

        if name not in self._active_skills:
            self._active_skills.add(name)
            if self.db:
                await self.db.activate_skill(name)
        return SkillActivation(session_id=session_id, skill=skill, actor=actor)

    async def deactivate_skill(self, *, name: str, session_id: str | None = None, actor: str = "system") -> SkillActivation:
        if not self.enabled:
            raise RuntimeError("Skills are disabled.")
        skill = self.registry.get_skill(name)
        if skill is None:
            raise SkillNotFoundError(f"Unknown skill: {name}")

        if name in self._active_skills:
            self._active_skills.remove(name)
            if self.db:
                await self.db.deactivate_skill(name)
        return SkillActivation(session_id=session_id, skill=skill, actor=actor)

    def build_available_skills_prompt(self, *, session_id: str | None = None) -> str:
        all_skills = self.list_skills()
        if not all_skills:
            return "<available_skills />"
        lines = ["<available_skills>"]
        for item in all_skills:
            active_tag = ' active="true"' if item.get("active") else ""
            lines.append(f"  <skill{active_tag}>")
            lines.append(f"    <name>{item['name']}</name>")
            lines.append(f"    <description>{item['description']}</description>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def build_active_skills_prompt(self, *, session_id: str | None = None) -> str:
        skills = self.get_active_skills()
        if not skills:
            return "<active_skills />"
        lines = ["<active_skills>"]
        for item in skills:
            lines.append(f"  <skill name=\"{item['name']}\">")
            lines.append("    <instructions>")
            for body_line in str(item.get("body") or "").splitlines():
                lines.append(f"      {body_line}")
            lines.append("    </instructions>")
            lines.append("  </skill>")
        lines.append("</active_skills>")
        return "\n".join(lines)


def create_skill_service(settings, db) -> SkillService:
    registry = SkillRegistry(root=settings.skills_root)
    registry.reload()
    return SkillService(
        registry=registry,
        db=db,
        enabled=bool(settings.skills_enabled),
    )
