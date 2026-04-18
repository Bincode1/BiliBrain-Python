import asyncio

import pytest

from bilibrain.skills.errors import SkillApprovalRequiredError, SkillError
from bilibrain.skills.policy import SkillPolicy, SkillPolicyAction, SkillPolicyRule
from bilibrain.skills.registry import SkillRegistry
from bilibrain.skills.service import SkillService


def _build_registry(tmp_path):
    root = tmp_path / "skills"
    skill_dir = root / "demo-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo skill for service tests.
allowed_tools:
  - read_file
metadata:
  when_to_use: Use this when the task needs demo guidance.
short-description: Demo coding helper
input-hint: Ask for a concrete file path or coding task before loading.
examples:
  - Review the current workspace coding flow.
  - Update the parser to support richer skill metadata.
---

Use ${BILIBRAIN_SKILL_DIR}/references/guide.md in tests.
""",
        encoding="utf-8",
    )
    (skill_dir / "references").mkdir(parents=True, exist_ok=True)
    (skill_dir / "references" / "guide.md").write_text("guide", encoding="utf-8")
    registry = SkillRegistry(root=root)
    registry.reload()
    return registry


def test_skill_service_reads_only_active_skill(tmp_path):
    service = SkillService(registry=_build_registry(tmp_path), db=None, enabled=True)

    asyncio.run(service.activate_skill(name="demo-skill", session_id="session-1", actor="test"))
    payload = service.read_skill(name="demo-skill", session_id="session-1", actor="agent")

    assert payload["name"] == "demo-skill"
    assert str(tmp_path / "skills" / "demo-skill" / "references" / "guide.md") in payload["body"]
    assert payload["variables"]["BILIBRAIN_SKILL_DIR"] == str(tmp_path / "skills" / "demo-skill")
    assert payload["resource_map"]["references/guide.md"] == str(tmp_path / "skills" / "demo-skill" / "references" / "guide.md")
    assert payload["usage_rules"][0] == "Resolve relative paths against $BILIBRAIN_SKILL_DIR."
    assert service.get_loaded_skills("session-1")[0]["name"] == "demo-skill"


def test_skill_service_rejects_inactive_skill(tmp_path):
    service = SkillService(registry=_build_registry(tmp_path), db=None, enabled=True)

    with pytest.raises(SkillError):
        service.read_skill(name="demo-skill", session_id="session-1", actor="agent")


def test_skill_service_formats_available_skills_prompt(tmp_path):
    service = SkillService(registry=_build_registry(tmp_path), db=None, enabled=True)

    asyncio.run(service.activate_skill(name="demo-skill", session_id="session-1", actor="test"))
    prompt = service.build_available_skills_prompt(session_id="session-1", actor="agent")

    assert "<available_skills>" in prompt
    assert "<name>demo-skill</name>" in prompt
    assert "<access>allow</access>" in prompt
    assert "<when_to_use>Use this when the task needs demo guidance.</when_to_use>" in prompt
    assert "<input_hint>Ask for a concrete file path or coding task before loading.</input_hint>" in prompt
    assert "<example>Review the current workspace coding flow.</example>" in prompt


def test_skill_service_hides_non_model_invocable_skill_from_agent_prompt(tmp_path):
    root = tmp_path / "skills"
    skill_dir = root / "manual-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: manual-skill
description: Manual-only skill.
disable-model-invocation: true
---

Use only from the workbench.
""",
        encoding="utf-8",
    )
    registry = SkillRegistry(root=root)
    registry.reload()
    service = SkillService(registry=registry, db=None, enabled=True)

    asyncio.run(service.activate_skill(name="manual-skill", session_id="session-1", actor="test"))
    prompt = service.build_available_skills_prompt(session_id="session-1", actor="agent")

    assert prompt == "<available_skills />"


def test_skill_service_requires_approval_for_ask_policy(tmp_path):
    policy = SkillPolicy(
        default_action=SkillPolicyAction.ALLOW,
        rules=(
            SkillPolicyRule(
                action=SkillPolicyAction.ASK,
                patterns=("demo-*",),
            ),
        ),
    )
    service = SkillService(registry=_build_registry(tmp_path), db=None, policy=policy, enabled=True)

    asyncio.run(service.activate_skill(name="demo-skill", session_id="session-1", actor="test"))
    with pytest.raises(SkillApprovalRequiredError):
        service.read_skill(name="demo-skill", session_id="session-1", actor="agent")

    service.approve_skill(name="demo-skill", session_id="session-1")
    payload = service.read_skill(name="demo-skill", session_id="session-1", actor="agent")
    assert payload["name"] == "demo-skill"


def test_skill_service_denies_manual_only_skill_to_agent(tmp_path):
    root = tmp_path / "skills"
    skill_dir = root / "manual-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: manual-skill
description: Manual-only skill.
disable-model-invocation: true
---

Use only from the workbench.
""",
        encoding="utf-8",
    )
    registry = SkillRegistry(root=root)
    registry.reload()
    service = SkillService(registry=registry, db=None, enabled=True)

    asyncio.run(service.activate_skill(name="manual-skill", session_id="session-1", actor="test"))
    with pytest.raises(SkillError, match="not visible to model actors"):
        service.read_skill(name="manual-skill", session_id="session-1", actor="agent")
