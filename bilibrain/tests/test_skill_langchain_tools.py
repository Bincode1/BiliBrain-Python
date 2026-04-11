import asyncio

from bilibrain.skills.langchain_tools import build_skill_langchain_tools


class _DummySkillService:
    def __init__(self) -> None:
        self.calls = []

    def activate_skill(self, *, name: str, session_id: str, actor: str = "system"):
        self.calls.append(("activate", name, session_id, actor))
        return type(
            "Activation",
            (),
            {
                "model_dump": lambda self: {
                    "session_id": session_id,
                    "skill": {"name": name},
                    "actor": actor,
                }
            },
        )()

    def get_active_skills(self, session_id: str):
        return [{"name": "demo-skill", "source": "system", "body": "hello"}]


def test_build_skill_langchain_tools_wraps_activation():
    service = _DummySkillService()
    tools = build_skill_langchain_tools(service, session_id="session-1", actor="agent")
    activate_tool = next(item for item in tools if item.name == "activate_skill")

    result = asyncio.run(activate_tool.ainvoke({"name": "demo-skill"}))

    assert result["session_id"] == "session-1"
    assert result["skill"]["name"] == "demo-skill"
    assert service.calls[0] == ("activate", "demo-skill", "session-1", "agent")


def test_build_skill_langchain_tools_emits_skill_events():
    events = []
    service = _DummySkillService()
    tools = build_skill_langchain_tools(
        service,
        session_id="session-1",
        actor="agent",
        event_callback=lambda event_type, payload: events.append((event_type, payload)),
    )
    activate_tool = next(item for item in tools if item.name == "activate_skill")

    asyncio.run(activate_tool.ainvoke({"name": "demo-skill"}))

    assert events[0][0] == "skill"
    assert events[0][1]["phase"] == "start"
    assert events[1][0] == "skill"
    assert events[1][1]["phase"] == "activated"
    assert events[2][0] == "skills"
