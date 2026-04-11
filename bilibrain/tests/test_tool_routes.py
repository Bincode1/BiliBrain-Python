from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bilibrain.api.errors import register_exception_handlers
from bilibrain.api.routes import tools
from bilibrain.tools.policy import ToolPolicy
from bilibrain.tools.runtime.local_dev import LocalDevRuntime
from bilibrain.tools.service import ToolService


def _build_test_app(tmp_path):
    service = ToolService(
        runtime=LocalDevRuntime(),
        workspace_base_root=tmp_path,
        policy=ToolPolicy(approval_required_for_command=False),
        enabled=True,
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(tools.router)
    app.state.runtime = SimpleNamespace(tool_service=service)
    return app


def test_list_tools_route_returns_registry_metadata(tmp_path):
    app = _build_test_app(tmp_path)
    client = TestClient(app)

    response = client.get("/api/tools")

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert any(item["name"] == "list_dir" for item in payload["tools"])
    assert any(item["name"] == "web_search" for item in payload["tools"])
    assert any(item["name"] == "browser_read_page" for item in payload["tools"])


def test_create_workspace_and_call_list_dir_route(tmp_path):
    app = _build_test_app(tmp_path)
    client = TestClient(app)

    create_response = client.post(
        "/api/tools/workspaces",
        json={
            "feature_name": "tools",
            "actor": "test",
        },
    )
    assert create_response.status_code == 200
    workspace = create_response.json()

    call_response = client.post(
        "/api/tools/call",
        json={
            "workspace_id": workspace["workspace_id"],
            "tool_name": "list_dir",
            "arguments": {"path": "."},
            "actor": "test",
        },
    )

    assert call_response.status_code == 200
    payload = call_response.json()
    assert payload["tool_name"] == "list_dir"
    assert payload["ok"] is True


def test_list_workspaces_route_returns_created_workspace(tmp_path):
    app = _build_test_app(tmp_path)
    client = TestClient(app)

    create_response = client.post(
        "/api/tools/workspaces",
        json={
            "feature_name": "tools",
            "title": "Demo Workspace",
            "actor": "test",
        },
    )
    assert create_response.status_code == 200

    list_response = client.get("/api/tools/workspaces?feature_name=tools")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["workspaces"]
    assert payload["workspaces"][0]["display_name"] == "Demo Workspace"
