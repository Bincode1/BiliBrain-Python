from __future__ import annotations

from pathlib import Path
from typing import Any

from bilibrain.skills.contracts import (
    SkillActivation,
    SkillDescriptor,
    SkillManifest,
)
from bilibrain.skills.errors import SkillError, SkillNotFoundError
from bilibrain.skills.errors import SkillApprovalRequiredError, SkillPolicyError
from bilibrain.skills.policy import (
    SkillPolicy,
    SkillPolicyAction,
    SkillPolicyDecision,
    build_skill_policy,
    evaluate_skill_request,
)
from bilibrain.skills.registry import SkillRegistry

SKILL_DIR_VARIABLE = "BILIBRAIN_SKILL_DIR"
_SKILL_DIR_PLACEHOLDERS = (
    f"${{{SKILL_DIR_VARIABLE}}}",
    "${SKILL_DIR}",
    "{{skill_root}}",
)


class SkillService:
    def __init__(
        self,
        *,
        registry: SkillRegistry,
        db,
        policy: SkillPolicy | None = None,
        enabled: bool = True,
    ) -> None:
        self.registry = registry
        self.db = db
        self.policy = policy or SkillPolicy()
        self.enabled = bool(enabled)
        self._active_skills: set[str] = set()
        self._approved_skills: dict[str, set[str]] = {}
        self._loaded_skills: dict[str, list[dict[str, Any]]] = {}
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

    def list_visible_skills(
        self,
        *,
        session_id: str | None = None,
        active_only: bool = True,
        actor: str = "agent",
        model_invocable_only: bool = False,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        skills = self.list_skills()
        if active_only:
            skills = [item for item in skills if item.get("active")]
        if model_invocable_only:
            skills = [item for item in skills if item.get("allow_model_invocation")]
        visible_skills: list[dict[str, Any]] = []
        for item in skills:
            decision = self.evaluate_skill_access(
                name=item["name"],
                session_id=session_id,
                actor=actor,
            )
            if decision.action == SkillPolicyAction.DENY:
                continue
            visible_skills.append(
                {
                    **item,
                    "visibility": decision.action.value,
                    "visibility_reason": decision.reason,
                }
            )
        return visible_skills

    def get_active_skills(
        self,
        session_id: str | None = None,
        *,
        actor: str = "workbench",
    ) -> list[dict[str, Any]]:
        return self.list_visible_skills(session_id=session_id, active_only=True, actor=actor)

    def get_skill(self, *, name: str) -> dict[str, Any]:
        if not self.enabled:
            raise SkillNotFoundError(f"Unknown skill: {name}")
        skill = self.registry.get_skill(name)
        if skill is None:
            raise SkillNotFoundError(f"Unknown skill: {name}")
        return skill.model_copy(update={"active": name in self._active_skills}).model_dump()

    def evaluate_skill_access(
        self,
        *,
        name: str,
        session_id: str | None = None,
        actor: str = "agent",
    ) -> SkillPolicyDecision:
        if not self.enabled:
            return SkillPolicyDecision(
                action=SkillPolicyAction.DENY,
                reason=f"Skill '{name}' is not available because skills are disabled.",
            )
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return SkillPolicyDecision(
                action=SkillPolicyAction.DENY,
                reason="Empty skill name is not allowed.",
            )
        if self.registry.get_skill(normalized_name) is None:
            raise SkillNotFoundError(f"Unknown skill: {normalized_name}")
        if normalized_name not in self._active_skills:
            raise SkillError(f"Skill '{normalized_name}' is not active.")
        skill = self.registry.get_skill(normalized_name)
        if skill is None:
            raise SkillNotFoundError(f"Unknown skill: {normalized_name}")
        if not skill.allow_model_invocation and normalized_actor not in {"system", "workbench"}:
            return SkillPolicyDecision(
                action=SkillPolicyAction.DENY,
                reason=f"Skill '{normalized_name}' is not visible to model actors.",
            )
        session_key = str(session_id or "").strip()
        if session_key and normalized_name in self._approved_skills.get(session_key, set()):
            return SkillPolicyDecision(
                action=SkillPolicyAction.ALLOW,
                reason=f"Skill '{normalized_name}' was preapproved for session '{session_key}'.",
            )
        return evaluate_skill_request(
            self.policy,
            skill_name=normalized_name,
            actor=actor,
        )

    def approve_skill(
        self,
        *,
        name: str,
        session_id: str,
    ) -> None:
        session_key = str(session_id or "").strip()
        if not session_key:
            raise SkillError("session_id is required to approve a skill.")
        approved = self._approved_skills.setdefault(session_key, set())
        approved.add(str(name or "").strip())

    def record_skill_load(
        self,
        *,
        name: str,
        session_id: str | None,
        actor: str,
        skill_root: str,
    ) -> None:
        session_key = str(session_id or "").strip()
        if not session_key:
            return
        loaded = self._loaded_skills.setdefault(session_key, [])
        loaded.append(
            {
                "name": name,
                "actor": actor,
                "skill_root": skill_root,
            }
        )

    def get_loaded_skills(self, session_id: str | None = None) -> list[dict[str, Any]]:
        session_key = str(session_id or "").strip()
        if not session_key:
            return []
        return list(self._loaded_skills.get(session_key, []))

    def _build_skill_variables(self, *, skill_root: str) -> dict[str, str]:
        resolved_root = str(skill_root or "").strip()
        return {
            SKILL_DIR_VARIABLE: resolved_root,
            "SKILL_DIR": resolved_root,
            "skill_root": resolved_root,
        }

    def _render_skill_body(self, *, body: str, skill_root: str) -> str:
        rendered = str(body or "")
        for placeholder in _SKILL_DIR_PLACEHOLDERS:
            rendered = rendered.replace(placeholder, str(skill_root or ""))
        return rendered

    def _build_resource_map(self, *, skill_root: str, resources: list[str]) -> dict[str, str]:
        base_path = Path(skill_root)
        mapping: dict[str, str] = {}
        for item in resources:
            relative_path = str(item or "").strip()
            if not relative_path:
                continue
            mapping[relative_path] = str((base_path / relative_path).resolve())
        return mapping

    def _build_usage_rules(self) -> list[str]:
        return [
            f"Resolve relative paths against ${SKILL_DIR_VARIABLE}.",
            "Do not auto-load references, scripts, assets, or agents directories.",
            "Use read_file or list_dir to inspect extra files on demand.",
            "Use run_command only when the skill explicitly requires script execution and the current approval policy allows it.",
        ]

    def read_skill(
        self,
        *,
        name: str,
        session_id: str | None = None,
        actor: str = "agent",
    ) -> dict[str, Any]:
        if not self.enabled:
            raise SkillNotFoundError(f"Unknown skill: {name}")
        skill = self.registry.get_skill(name)
        if skill is None:
            raise SkillNotFoundError(f"Unknown skill: {name}")
        decision = self.evaluate_skill_access(name=name, session_id=session_id, actor=actor)
        if decision.action == SkillPolicyAction.DENY:
            raise SkillPolicyError(decision.reason)
        if decision.action == SkillPolicyAction.ASK:
            raise SkillApprovalRequiredError(decision.reason)
        payload = skill.model_copy(update={"active": True}).model_dump()
        skill_root = payload["directory_path"]
        payload["variables"] = self._build_skill_variables(skill_root=skill_root)
        payload["body"] = self._render_skill_body(
            body=payload["body"],
            skill_root=skill_root,
        )
        payload["resource_map"] = self._build_resource_map(
            skill_root=skill_root,
            resources=list(payload.get("resources") or []),
        )
        payload["usage_rules"] = self._build_usage_rules()
        self.record_skill_load(
            name=payload["name"],
            session_id=session_id,
            actor=actor,
            skill_root=skill_root,
        )
        return payload

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

    def build_available_skills_prompt(
        self,
        *,
        session_id: str | None = None,
        actor: str = "agent",
    ) -> str:
        visible_skills = self.list_visible_skills(
            session_id=session_id,
            active_only=True,
            actor=actor,
            model_invocable_only=True,
        )
        if not visible_skills:
            return "<available_skills />"
        lines = ["<available_skills>"]
        for item in visible_skills:
            lines.append("  <skill>")
            lines.append(f"    <name>{item['name']}</name>")
            summary = str(item.get("short_description") or item["description"]).strip()
            lines.append(f"    <description>{summary}</description>")
            visibility = str(item.get("visibility") or "").strip()
            if visibility:
                lines.append(f"    <access>{visibility}</access>")
            when_to_use = str(item.get("when_to_use") or "").strip()
            if when_to_use:
                lines.append(f"    <when_to_use>{when_to_use}</when_to_use>")
            input_hint = str(item.get("input_hint") or "").strip()
            if input_hint:
                lines.append(f"    <input_hint>{input_hint}</input_hint>")
            allowed_tools = list(item.get("allowed_tools") or [])
            if allowed_tools:
                lines.append("    <allowed_tools>")
                for tool_name in allowed_tools:
                    lines.append(f"      <tool>{tool_name}</tool>")
                lines.append("    </allowed_tools>")
            resource_count = len(item.get("resources") or [])
            if resource_count:
                lines.append(f"    <resource_count>{resource_count}</resource_count>")
            examples = list(item.get("examples") or [])
            if examples:
                lines.append("    <examples>")
                for example in examples[:3]:
                    lines.append(f"      <example>{example}</example>")
                lines.append("    </examples>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)


def create_skill_service(settings, db) -> SkillService:
    registry = SkillRegistry(root=settings.skills_root)
    registry.reload()
    return SkillService(
        registry=registry,
        db=db,
        policy=build_skill_policy(settings),
        enabled=bool(settings.skills_enabled),
    )
