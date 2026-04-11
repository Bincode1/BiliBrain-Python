from bilibrain.skills.contracts import SkillSource, SkillSourceConfig
from bilibrain.skills.registry import SkillRegistry


def _write_skill(root, directory_name, *, name, description, body):
    skill_dir = root / directory_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: {description}
---

{body}
""",
        encoding="utf-8",
    )


def test_skill_registry_prefers_higher_precedence_sources(tmp_path):
    system_root = tmp_path / "system"
    user_root = tmp_path / "user"
    repo_root = tmp_path / "repo"
    _write_skill(system_root, "shared", name="shared-skill", description="system", body="system body")
    _write_skill(user_root, "shared", name="shared-skill", description="user", body="user body")
    _write_skill(repo_root, "shared", name="shared-skill", description="repo", body="repo body")

    registry = SkillRegistry(
        source_configs=[
            SkillSourceConfig(source=SkillSource.SYSTEM, root=system_root, precedence=0),
            SkillSourceConfig(source=SkillSource.USER, root=user_root, precedence=10),
            SkillSourceConfig(source=SkillSource.REPO, root=repo_root, precedence=20),
        ]
    )

    skill = registry.get_skill("shared-skill")

    assert skill is not None
    assert skill.source == SkillSource.REPO
    assert skill.description == "repo"
    assert "repo body" in skill.body


def test_skill_registry_collects_resources(tmp_path):
    root = tmp_path / "system"
    _write_skill(root, "demo", name="demo", description="demo skill", body="demo body")
    refs_dir = root / "demo" / "references"
    refs_dir.mkdir(parents=True)
    (refs_dir / "guide.md").write_text("hello", encoding="utf-8")

    registry = SkillRegistry(source_configs=[SkillSourceConfig(source=SkillSource.SYSTEM, root=root, precedence=0)])

    skill = registry.get_skill("demo")

    assert skill is not None
    assert "references/guide.md" in skill.resources
