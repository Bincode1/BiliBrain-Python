from __future__ import annotations

import logging
from pathlib import Path

from bilibrain.skills.contracts import SkillDescriptor, SkillManifest, SkillSource, SkillSourceConfig
from bilibrain.skills.errors import SkillParseError
from bilibrain.skills.parser import parse_skill_file

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(
        self,
        *,
        root: Path | None = None,
        source_configs: list[SkillSourceConfig] | None = None,
    ) -> None:
        if source_configs:
            ordered_configs = sorted(source_configs, key=lambda item: item.precedence)
        elif root is not None:
            ordered_configs = [
                SkillSourceConfig(
                    source=SkillSource.SYSTEM,
                    root=Path(root),
                    precedence=0,
                )
            ]
        else:
            raise ValueError("SkillRegistry requires either root or source_configs.")
        self.source_configs = ordered_configs
        self.root = ordered_configs[0].root
        self._skills: dict[str, SkillManifest] = {}

    def reload(self) -> dict[str, SkillManifest]:
        skills: dict[str, SkillManifest] = {}
        skill_precedence: dict[str, int] = {}
        for source_config in self.source_configs:
            root = source_config.root
            if not root.exists():
                continue
            for skill_file in sorted(root.rglob("SKILL.md")):
                try:
                    parsed = parse_skill_file(skill_file)
                except SkillParseError:
                    logger.warning("Skipping invalid skill file: %s", skill_file)
                    continue
                manifest = SkillManifest(
                    name=parsed.name,
                    description=parsed.description,
                    source=source_config.source,
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
                existing_precedence = skill_precedence.get(manifest.name, -10**9)
                if source_config.precedence >= existing_precedence:
                    skills[manifest.name] = manifest
                    skill_precedence[manifest.name] = source_config.precedence
        self._skills = skills
        return dict(self._skills)

    def list_skills(self) -> list[SkillDescriptor]:
        if not self._skills:
            self.reload()
        return [SkillDescriptor(**skill.model_dump(exclude={"body"})) for skill in self._skills.values()]

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
