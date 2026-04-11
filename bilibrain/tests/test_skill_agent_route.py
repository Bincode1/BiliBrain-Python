from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bilibrain.api.errors import register_exception_handlers
from bilibrain.api.routes import skill_agent


def test_skill_agent_route_returns_service_payload(monkeypatch):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(skill_agent.router)
    app.state.runtime = SimpleNamespace()

    async def fake_answer_with_skill_agent(runtime, **kwargs):
        assert kwargs["query"] == "请整理当前工作区"
        assert kwargs["conversation_id"] == 12
        return {
            "conversation_id": 12,
            "session_id": "conversation-12",
            "workspace_id": "skill-agent-12",
            "answer": "已整理",
            "active_skills": [{"name": "workspace-coding"}],
        }

    monkeypatch.setattr(skill_agent, "answer_with_skill_agent", fake_answer_with_skill_agent)

    client = TestClient(app)
    response = client.post(
        "/api/skill-agent/ask",
        json={
            "query": "请整理当前工作区",
            "conversation_id": 12,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "conversation-12"
    assert payload["answer"] == "已整理"


def test_skill_agent_resume_route_returns_service_payload(monkeypatch):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(skill_agent.router)
    app.state.runtime = SimpleNamespace()

    async def fake_resume_unified_agent_turn(runtime, **kwargs):
        assert kwargs["session_id"] == "conversation-12"
        assert kwargs["decision"] == {"type": "approve"}
        return {
            "status": "completed",
            "conversation_id": 12,
            "session_id": "conversation-12",
            "workspace_id": "skill-agent-12",
            "answer": "继续执行完成",
        }

    monkeypatch.setattr(skill_agent, "resume_unified_agent_turn", fake_resume_unified_agent_turn)

    client = TestClient(app)
    response = client.post(
        "/api/skill-agent/resume",
        json={
            "conversation_id": 12,
            "session_id": "conversation-12",
            "decision": {"type": "approve"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "继续执行完成"


def test_skill_agent_stream_route_returns_event_stream(monkeypatch):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(skill_agent.router)
    app.state.runtime = SimpleNamespace()

    async def fake_stream_answer_with_skill_agent_events(runtime, **kwargs):
        yield "event: conversation\ndata: {\"conversation_id\": 12}\n\n"
        yield "event: answer\ndata: {\"delta\": \"已整理\"}\n\n"
        yield "event: done\ndata: {}\n\n"

    monkeypatch.setattr(skill_agent, "stream_answer_with_skill_agent_events", fake_stream_answer_with_skill_agent_events)

    client = TestClient(app)
    response = client.post(
        "/api/skill-agent/ask/stream",
        json={
            "query": "请整理当前工作区",
            "conversation_id": 12,
        },
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: answer" in response.text
