from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bilibrain.api.errors import register_exception_handlers
from bilibrain.api.routes import skills
from bilibrain.skills.contracts import SkillSource, SkillSourceConfig
from bilibrain.skills.registry import SkillRegistry
from bilibrain.skills.service import SkillService


def _build_test_app(tmp_path):
    root = tmp_path / "system"
    skill_dir = root / "demo"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: demo-skill
description: Demo skill from the route tests.
---

Use this skill when testing routes.
""",
        encoding="utf-8",
    )
    service = SkillService(
        registry=SkillRegistry(source_configs=[SkillSourceConfig(source=SkillSource.SYSTEM, root=root, precedence=0)]),
        enabled=True,
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(skills.router)
    app.state.runtime = SimpleNamespace(skill_service=service)
    return app


def test_list_skills_route_returns_skill_catalog(tmp_path):
    app = _build_test_app(tmp_path)
    client = TestClient(app)

    response = client.get("/api/skills")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["skills"]
    assert payload["skills"][0]["name"] == "demo-skill"


def test_activate_skill_route_returns_activation_payload(tmp_path):
    app = _build_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/skills/activate",
        json={
            "name": "demo-skill",
            "session_id": "session-1",
            "actor": "test",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "session-1"
    assert payload["skill"]["name"] == "demo-skill"


def test_get_active_skills_route_returns_prompt(tmp_path):
    app = _build_test_app(tmp_path)
    client = TestClient(app)
    activate_response = client.post(
        "/api/skills/activate",
        json={
            "name": "demo-skill",
            "session_id": "session-1",
            "actor": "test",
        },
    )
    assert activate_response.status_code == 200

    response = client.get("/api/skills/sessions/session-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["active_skills"]
    assert "available_skills" in payload["available_skills_prompt"]
