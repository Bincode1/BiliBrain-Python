from __future__ import annotations

from pathlib import Path

from bilibrain.skills.contracts import SkillDescriptor, SkillManifest, SkillSourceConfig
from bilibrain.skills.parser import parse_skill_file


class SkillRegistry:
    def __init__(self, *, source_configs: list[SkillSourceConfig] | None = None) -> None:
        self.source_configs = source_configs or []
        self._skills: dict[str, SkillManifest] = {}

    def reload(self) -> dict[str, SkillManifest]:
        skills: dict[str, SkillManifest] = {}
        for source_config in sorted(self.source_configs, key=lambda item: item.precedence):
            if not source_config.enabled:
                continue
            root = Path(source_config.root)
            if not root.exists():
                continue
            for skill_file in sorted(root.rglob("SKILL.md")):
                parsed = parse_skill_file(skill_file)
                descriptor = SkillManifest(
                    name=parsed.name,
                    description=parsed.description,
                    source=source_config.source,
                    skill_path=str(skill_file),
                    directory_path=str(skill_file.parent),
                    allow_model_invocation=parsed.allow_model_invocation,
                    allowed_tools=parsed.allowed_tools,
                    requires=parsed.requires,
                    metadata=parsed.metadata,
                    resources=_collect_skill_resources(skill_file.parent),
                    precedence=source_config.precedence,
                    body=parsed.body,
                    source_root=str(root),
                )
                skills[descriptor.name] = descriptor
        self._skills = skills
        return dict(self._skills)

    def list_skills(self) -> list[SkillDescriptor]:
        if not self._skills:
            self.reload()
        return [SkillDescriptor(**skill.model_dump(exclude={"body", "source_root"})) for skill in self._skills.values()]

    def get_skill(self, name: str) -> SkillManifest | None:
        if not self._skills:
            self.reload()
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
