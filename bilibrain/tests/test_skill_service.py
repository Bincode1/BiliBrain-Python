from bilibrain.skills.contracts import SkillSource, SkillSourceConfig
from bilibrain.skills.errors import SkillPolicyError
from bilibrain.skills.registry import SkillRegistry
from bilibrain.skills.service import SkillService


def _build_registry(tmp_path, *, source=SkillSource.SYSTEM):
    root = tmp_path / source.value
    skill_dir = root / "demo"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo skill for service tests.
---

Use this skill in tests.
""",
        encoding="utf-8",
    )
    return SkillRegistry(source_configs=[SkillSourceConfig(source=source, root=root, precedence=0 if source == SkillSource.SYSTEM else 20)])


def test_skill_service_activates_skill_and_tracks_session(tmp_path):
    service = SkillService(registry=_build_registry(tmp_path), enabled=True)

    activation = service.activate_skill(name="demo-skill", session_id="session-1", actor="test")

    assert activation.session_id == "session-1"
    assert activation.skill.name == "demo-skill"
    active = service.get_active_skills("session-1")
    assert len(active) == 1
    assert active[0]["name"] == "demo-skill"


def test_skill_service_blocks_untrusted_repo_skills(tmp_path):
    service = SkillService(
        registry=_build_registry(tmp_path, source=SkillSource.REPO),
        enabled=True,
        allow_repo_skills=False,
    )

    try:
        service.activate_skill(name="demo-skill", session_id="session-1", actor="test")
    except SkillPolicyError as exc:
        assert "trusted" in str(exc).lower()
    else:
        raise AssertionError("expected SkillPolicyError")


def test_skill_service_formats_available_skills_prompt(tmp_path):
    service = SkillService(registry=_build_registry(tmp_path), enabled=True)

    prompt = service.build_available_skills_prompt()

    assert "<available_skills>" in prompt
    assert "<name>demo-skill</name>" in prompt
