import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bilibrain.services import skill_agent as module
from bilibrain.tools.policy import ToolPolicy


def test_build_skill_agent_session_id_uses_conversation_id():
    assert module.build_skill_agent_session_id(conversation_id=12) == "conversation-12"
    assert module.build_skill_agent_session_id(conversation_id=12, explicit_session_id="custom-session") == "custom-session"


def test_build_skill_agent_prompt_contains_skills_and_workspace():
    runtime = SimpleNamespace(
        skill_service=SimpleNamespace(
            build_available_skills_prompt=lambda **_: "<available_skills><skill /></available_skills>",
        ),
        tool_service=SimpleNamespace(
            list_tools=lambda: [
                {"name": "read_file", "description": "Read file", "enabled": True},
                {"name": "run_command", "description": "Run command", "enabled": True},
            ]
        ),
    )

    prompt = module.build_skill_agent_prompt(
        runtime,
        session_id="conversation-1",
        workspace_id="skill-agent-1",
        actor="skill-agent",
    )

    assert "conversation-1" not in prompt
    assert "skill-agent-1" in prompt
    assert "<available_skills>" in prompt
    assert "<active_skills>" not in prompt
    assert "skill(name)" in prompt
    assert "read_file" in prompt


def test_answer_with_skill_agent_uses_conversation_and_workspace(monkeypatch):
    appended_messages = []

    class DummyDb:
        def __init__(self) -> None:
            self.conversation = {"conversation_id": 7, "title": "", "folder_id": None}

        def get_chat_conversation(self, conversation_id):
            return self.conversation if int(conversation_id) == 7 else None

        def create_chat_conversation(self, folder_id, title=""):
            return self.conversation

        def list_recent_chat_messages_by_turns(self, conversation_id, *, keep_turns):
            return [{"role": "user", "content": "之前的问题"}]

        def append_chat_message(self, conversation_id, role, content, sources=None, answer_mode=None, route_mode=None):
            appended_messages.append((conversation_id, role, content))
            return {"conversation_id": conversation_id, "role": role, "content": content}

    class DummySkillService:
        def build_available_skills_prompt(self, *, session_id=None, actor="agent"):
            return "<available_skills />"

        def get_active_skills(self, session_id):
            return [{"name": "workspace-coding", "source": "system", "body": "..."}]

    class DummyToolService:
        def list_tools(self):
            return [{"name": "read_file", "description": "Read file", "enabled": True}]

        def create_workspace(self, *, feature_name, conversation_id=None, title=None, actor="system"):
            return {"workspace_id": f"{feature_name}-{conversation_id}", "title": title}

    runtime = SimpleNamespace(
        db=DummyDb(),
        skill_service=DummySkillService(),
        tool_service=DummyToolService(),
        qwen=SimpleNamespace(model=object()),
        settings=SimpleNamespace(chat_recent_turns_to_keep=5),
    )

    monkeypatch.setattr(module, "build_skill_langchain_tools", lambda *args, **kwargs: ["skill-tool"])
    monkeypatch.setattr(module, "build_langchain_tools", lambda *args, **kwargs: ["workspace-tool"])

    # Mock the agent loop to return a completed answer
    async def fake_run_loop(runtime, *, messages, tools, session_id, actor, event_callback=None):
        return "技能代理回答", None

    monkeypatch.setattr(module, "_run_skill_agent_loop", fake_run_loop)

    payload = asyncio.run(
        module.answer_with_skill_agent(
            runtime,
            query="现在帮我整理一下",
            conversation_id=7,
        )
    )

    assert payload["status"] == "completed"
    assert payload["conversation_id"] == 7
    assert payload["session_id"] == "conversation-7"
    assert payload["workspace_id"] == "skill-agent-7"
    assert payload["answer"] == "技能代理回答"
    assert appended_messages[0] == (7, "user", "现在帮我整理一下")
    assert appended_messages[1] == (7, "assistant", "技能代理回答")


def test_answer_with_skill_agent_returns_pending_approval(monkeypatch):
    class DummyDb:
        def __init__(self) -> None:
            self.conversation = {"conversation_id": 9, "title": "", "folder_id": None}

        def get_chat_conversation(self, conversation_id):
            return self.conversation if int(conversation_id) == 9 else None

        def create_chat_conversation(self, folder_id, title=""):
            return self.conversation

        def list_recent_chat_messages_by_turns(self, conversation_id, *, keep_turns):
            return []

        def append_chat_message(self, conversation_id, role, content, sources=None, answer_mode=None, route_mode=None):
            return {"conversation_id": conversation_id, "role": role, "content": content}

    runtime = SimpleNamespace(
        db=DummyDb(),
        skill_service=SimpleNamespace(
            build_available_skills_prompt=lambda **_: "<available_skills />",
            get_active_skills=lambda session_id: [],
        ),
        tool_service=SimpleNamespace(
            list_tools=lambda: [{"name": "run_command", "description": "Run command", "enabled": True}],
            create_workspace=lambda **kwargs: {"workspace_id": "skill-agent-9"},
        ),
        qwen=SimpleNamespace(model=object()),
        settings=SimpleNamespace(chat_recent_turns_to_keep=5),
    )

    monkeypatch.setattr(module, "build_skill_langchain_tools", lambda *args, **kwargs: ["skill-tool"])
    monkeypatch.setattr(module, "build_langchain_tools", lambda *args, **kwargs: ["workspace-tool"])

    # Mock the agent loop to return a pending approval
    async def fake_run_loop(runtime, *, messages, tools, session_id, actor, event_callback=None):
        return "", {
            "interrupt_id": "int-1",
            "action_requests": [
                {
                    "name": "run_command",
                    "args": {"command": "python -V"},
                    "description": "approve this command",
                }
            ],
            "review_configs": [
                {
                    "action_name": "run_command",
                    "allowed_decisions": ["approve", "edit", "reject"],
                }
            ],
        }

    monkeypatch.setattr(module, "_run_skill_agent_loop", fake_run_loop)

    payload = asyncio.run(
        module.answer_with_skill_agent(
            runtime,
            query="运行一个命令",
            conversation_id=9,
        )
    )

    assert payload["status"] == "pending_approval"
    assert payload["approval_request"]["interrupt_id"] == "int-1"
    assert payload["approval_request"]["action_requests"][0]["name"] == "run_command"


def test_resume_skill_agent_turn_returns_completed_response(monkeypatch):
    appended_messages = []

    class DummyDb:
        def __init__(self) -> None:
            self.conversation = {"conversation_id": 11, "title": "", "folder_id": None}

        def get_chat_conversation(self, conversation_id):
            return self.conversation if int(conversation_id) == 11 else None

        def append_chat_message(self, conversation_id, role, content, sources=None, answer_mode=None, route_mode=None):
            appended_messages.append((conversation_id, role, content))
            return {"conversation_id": conversation_id, "role": role, "content": content}

        def list_recent_chat_messages_by_turns(self, conversation_id, *, keep_turns):
            return []

    runtime = SimpleNamespace(
        db=DummyDb(),
        skill_service=SimpleNamespace(
            build_available_skills_prompt=lambda **_: "<available_skills />",
            get_active_skills=lambda session_id: [{"name": "workspace-coding"}],
            approve_skill=lambda **kwargs: None,
        ),
        tool_service=SimpleNamespace(
            list_tools=lambda: [{"name": "run_command", "description": "Run command", "enabled": True}],
            create_workspace=lambda **kwargs: {"workspace_id": "skill-agent-11"},
        ),
        qwen=SimpleNamespace(model=object()),
        settings=SimpleNamespace(chat_recent_turns_to_keep=5),
    )

    monkeypatch.setattr(module, "build_skill_langchain_tools", lambda *args, **kwargs: ["skill-tool"])
    monkeypatch.setattr(module, "build_langchain_tools", lambda *args, **kwargs: ["workspace-tool"])

    # Mock tool executor + agent loop
    fake_tool_result = '{"ok": true, "output": "done"}'

    def fake_build_tool_executor(tools, *, runtime, event_callback=None):
        async def execute(name, arguments):
            return fake_tool_result
        return {}, execute

    monkeypatch.setattr(module, "_build_tool_executor", fake_build_tool_executor)

    async def fake_run_loop(runtime, *, messages, tools, session_id, actor, event_callback=None):
        return "恢复执行完成", None

    monkeypatch.setattr(module, "_run_skill_agent_loop", fake_run_loop)

    payload = asyncio.run(
        module.resume_skill_agent_turn(
            runtime,
            session_id="conversation-11",
            decision={"type": "approve"},
            conversation_id=11,
        )
    )

    assert payload["status"] == "completed"
    assert payload["answer"] == "恢复执行完成"
    assert appended_messages[0] == (11, "assistant", "恢复执行完成")


def test_resume_skill_agent_turn_rejects_pending_action():
    appended_messages = []

    class DummyDb:
        def __init__(self) -> None:
            self.conversation = {"conversation_id": 13, "title": "", "folder_id": None}

        def get_chat_conversation(self, conversation_id):
            return self.conversation if int(conversation_id) == 13 else None

        def append_chat_message(self, conversation_id, role, content, sources=None, answer_mode=None, route_mode=None):
            appended_messages.append((conversation_id, role, content))
            return {"conversation_id": conversation_id, "role": role, "content": content}

        def list_recent_chat_messages_by_turns(self, conversation_id, *, keep_turns):
            return []

    runtime = SimpleNamespace(
        db=DummyDb(),
        skill_service=SimpleNamespace(
            build_available_skills_prompt=lambda **_: "<available_skills />",
            get_active_skills=lambda session_id: [],
        ),
        tool_service=SimpleNamespace(
            list_tools=lambda: [],
            create_workspace=lambda **kwargs: {"workspace_id": "skill-agent-13"},
        ),
        qwen=SimpleNamespace(model=object()),
        settings=SimpleNamespace(chat_recent_turns_to_keep=5),
    )

    payload = asyncio.run(
        module.resume_skill_agent_turn(
            runtime,
            session_id="conversation-13",
            decision={"type": "reject", "message": "用户拒绝了 skill 加载。"},
            conversation_id=13,
        )
    )

    assert payload["status"] == "completed"
    assert payload["answer"] == "用户拒绝了 skill 加载。"
    assert appended_messages[0] == (13, "assistant", "用户拒绝了 skill 加载。")


def test_format_interrupt_keeps_file_action_payload():
    runtime = SimpleNamespace(tool_service=None)

    # _format_interrupt now accepts a dict-like interrupt or object with .value and .id
    class FakeInterrupt:
        id = "int-file-1"
        value = {
            "action_requests": [
                {
                    "name": "write_file",
                    "args": {"path": "notes.txt", "content": "hello"},
                    "description": "approve this file write",
                }
            ],
            "review_configs": [
                {
                    "action_name": "write_file",
                    "allowed_decisions": ["approve", "edit", "reject"],
                }
            ],
        }

    payload = module._format_interrupt(runtime, FakeInterrupt())

    assert payload["interrupt_id"] == "int-file-1"
    assert payload["action_requests"][0]["name"] == "write_file"
    assert payload["action_requests"][0]["args"]["path"] == "notes.txt"
    assert payload["action_requests"][0]["args"]["content"] == "hello"
    assert payload["action_requests"][0]["policy_blocked"] is False


def test_format_interrupt_marks_blocked_command():
    runtime = SimpleNamespace(
        tool_service=SimpleNamespace(
            policy=ToolPolicy(blocked_command_prefixes=[["rm"]]),
        )
    )

    class FakeInterrupt:
        id = "int-cmd-1"
        value = {
            "action_requests": [
                {
                    "name": "run_command",
                    "args": {"command": "rm -f test.txt"},
                    "description": "approve this command",
                }
            ],
            "review_configs": [
                {
                    "action_name": "run_command",
                    "allowed_decisions": ["approve", "edit", "reject"],
                }
            ],
        }

    payload = module._format_interrupt(runtime, FakeInterrupt())

    assert payload["action_requests"][0]["policy_blocked"] is True
    assert payload["action_requests"][0]["policy_allowed"] is False
    assert payload["action_requests"][0]["policy_reason"] == "Blocked command prefix: rm"
