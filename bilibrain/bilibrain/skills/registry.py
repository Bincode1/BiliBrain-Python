from __future__ import annotations

import logging
from pathlib import Path

from bilibrain.skills.contracts import SkillDescriptor, SkillManifest
from bilibrain.skills.errors import SkillParseError
from bilibrain.skills.parser import parse_skill_file

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self, *, root: Path) -> None:
        self.root = root
        self._skills: dict[str, SkillManifest] = {}

    def reload(self) -> dict[str, SkillManifest]:
        skills: dict[str, SkillManifest] = {}
        if not self.root.exists():
            self._skills = skills
            return dict(self._skills)
        for skill_file in sorted(self.root.rglob("SKILL.md")):
            try:
                parsed = parse_skill_file(skill_file)
            except SkillParseError:
                logger.warning("Skipping invalid skill file: %s", skill_file)
                continue
            manifest = SkillManifest(
                name=parsed.name,
                description=parsed.description,
                short_description=parsed.short_description,
                when_to_use=parsed.when_to_use,
                input_hint=parsed.input_hint,
                examples=parsed.examples,
                skill_path=str(skill_file),
                directory_path=str(skill_file.parent),
                allow_model_invocation=parsed.allow_model_invocation,
                allowed_tools=parsed.allowed_tools,
                requires=parsed.requires,
                metadata=parsed.metadata,
                resources=_collect_skill_resources(skill_file.parent),
                body=parsed.body,
            )
            skills[manifest.name] = manifest
        self._skills = skills
        return dict(self._skills)

    def list_skills(self) -> list[SkillDescriptor]:
        if not self._skills:
            self.reload()
        return [SkillDescriptor(**skill.model_dump(exclude={"body"})) for skill in self._skills.values()]

    def get_skill(self, name: str) -> SkillManifest | None:
        return self._skills.get(name)


def _collect_skill_resources(skill_dir: Path) -> list[str]:
    resources: list[str] = []
    for folder_name in ("references", "scripts", "assets", "agents"):
        folder = skill_dir / folder_name
        if not folder.exists():
            continue
        for file_path in sorted(folder.rglob("*")):
            if file_path.is_file():
                resources.append(file_path.relative_to(skill_dir).as_posix())
    return resources
