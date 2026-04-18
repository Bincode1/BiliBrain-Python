import asyncio

import pytest

from bilibrain.skills.errors import SkillApprovalRequiredError, SkillError
from bilibrain.skills.langchain_tools import build_skill_langchain_tools


class _DummySkillService:
    def __init__(self) -> None:
        self.calls = []

    def read_skill(self, *, name: str, session_id: str, actor: str):
        self.calls.append(("read_skill", name, session_id, actor))
        if name != "demo-skill":
            raise SkillError(f"Skill '{name}' is not active.")
        return {
            "name": name,
            "description": "Demo skill",
            "body": "# Demo\nUse ${BILIBRAIN_SKILL_DIR}/references/guide.md.",
            "directory_path": "/skills/demo-skill",
            "skill_path": "/skills/demo-skill/SKILL.md",
            "variables": {"BILIBRAIN_SKILL_DIR": "/skills/demo-skill"},
            "resources": ["references/guide.md", "scripts/run.py"],
            "resource_map": {
                "references/guide.md": "/skills/demo-skill/references/guide.md",
                "scripts/run.py": "/skills/demo-skill/scripts/run.py",
            },
            "allowed_tools": ["read_file", "run_command"],
            "usage_rules": ["Resolve relative paths against $BILIBRAIN_SKILL_DIR."],
        }

    def get_active_skills(self, session_id: str):
        return [{"name": "demo-skill", "description": "Demo skill"}]


def test_build_skill_langchain_tools_reads_full_skill_payload():
    service = _DummySkillService()
    tools = build_skill_langchain_tools(service, session_id="session-1", actor="agent")
    skill_tool = next(item for item in tools if item.name == "skill")

    result = asyncio.run(skill_tool.ainvoke({"name": "demo-skill"}))

    assert result["name"] == "demo-skill"
    assert result["content"] == "# Demo\nUse ${BILIBRAIN_SKILL_DIR}/references/guide.md."
    assert result["skill_root"] == "/skills/demo-skill"
    assert result["variables"]["BILIBRAIN_SKILL_DIR"] == "/skills/demo-skill"
    assert result["resources"] == ["references/guide.md", "scripts/run.py"]
    assert result["resource_map"]["references/guide.md"] == "/skills/demo-skill/references/guide.md"
    assert result["usage_rules"][0] == "Resolve relative paths against $BILIBRAIN_SKILL_DIR."
    assert service.calls[0] == ("read_skill", "demo-skill", "session-1", "agent")


def test_build_skill_langchain_tools_emits_skill_events():
    events = []
    service = _DummySkillService()
    tools = build_skill_langchain_tools(
        service,
        session_id="session-1",
        actor="agent",
        event_callback=lambda event_type, payload: events.append((event_type, payload)),
    )
    skill_tool = next(item for item in tools if item.name == "skill")

    asyncio.run(skill_tool.ainvoke({"name": "demo-skill"}))

    assert events[0][0] == "skill"
    assert events[0][1]["phase"] == "start"
    assert events[1][0] == "skill"
    assert events[1][1]["phase"] == "loaded"
    assert events[2][0] == "skills"


def test_build_skill_langchain_tools_rejects_inactive_skill():
    service = _DummySkillService()
    tools = build_skill_langchain_tools(service, session_id="session-1", actor="agent")
    skill_tool = next(item for item in tools if item.name == "skill")

    with pytest.raises(SkillError):
        asyncio.run(skill_tool.ainvoke({"name": "missing-skill"}))


def test_build_skill_langchain_tools_emits_approval_required():
    events = []

    class _ApprovalSkillService(_DummySkillService):
        def read_skill(self, *, name: str, session_id: str, actor: str):
            raise SkillApprovalRequiredError("skill requires approval")

    service = _ApprovalSkillService()
    tools = build_skill_langchain_tools(
        service,
        session_id="session-1",
        actor="agent",
        event_callback=lambda event_type, payload: events.append((event_type, payload)),
    )
    skill_tool = next(item for item in tools if item.name == "skill")

    with pytest.raises(SkillApprovalRequiredError):
        asyncio.run(skill_tool.ainvoke({"name": "demo-skill"}))

    assert events[0][0] == "skill"
    assert events[0][1]["phase"] == "start"
    assert events[1][0] == "skill"
    assert events[1][1]["phase"] == "approval_required"
