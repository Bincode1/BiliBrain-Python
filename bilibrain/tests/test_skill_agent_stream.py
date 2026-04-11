import asyncio
from types import SimpleNamespace

from bilibrain.services import skill_agent as module


def test_chunk_text_splits_payload():
    chunks = module._chunk_text("abcdefghijklmnopqrstuvwxyz", chunk_size=10)
    assert chunks == ["abcdefghij", "klmnopqrst", "uvwxyz"]


def test_stream_answer_with_skill_agent_events_emits_sse_sequence(monkeypatch):
    runtime = SimpleNamespace()

    monkeypatch.setattr(
        module,
        "ensure_skill_agent_conversation",
        lambda runtime, conversation_id: {"conversation_id": 5},
    )

    async def fake_execute(runtime, **kwargs):
        return {
            "conversation_id": 5,
            "session_id": "conversation-5",
            "workspace_id": "skill-agent-5",
            "answer": "技能代理返回了一段较长的回答",
            "active_skills": [{"name": "workspace-coding"}],
        }

    monkeypatch.setattr(module, "_execute_skill_agent_turn", fake_execute)

    async def collect():
        events = []
        async for item in module.stream_answer_with_skill_agent_events(runtime, query="hello", conversation_id=5):
            events.append(item)
        return events

    payload = asyncio.run(collect())

    assert any("event: conversation" in item for item in payload)
    assert any("event: status" in item for item in payload)
    assert any("event: answer" in item for item in payload)
    assert any("event: skills" in item for item in payload)
    assert any("event: done" in item for item in payload)
