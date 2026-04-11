import asyncio

from bilibrain.tools.errors import ToolApprovalRequiredError
from bilibrain.tools.policy import ToolPolicy
from bilibrain.tools.runtime.local_dev import LocalDevRuntime
from bilibrain.tools.service import ToolService


def test_tool_service_dispatches_registered_tool(tmp_path):
    service = ToolService(
        registry=None,
        runtime=LocalDevRuntime(),
        workspace_base_root=tmp_path,
        policy=ToolPolicy(approval_required_for_command=False),
        enabled=True,
    )
    workspace = service.create_workspace(feature_name="tools", actor="test")

    result = asyncio.run(
        service.call_tool(
            workspace_id=workspace["workspace_id"],
            tool_name="list_dir",
            arguments={"path": "."},
            actor="test",
        )
    )

    assert result.tool_name == "list_dir"
    assert result.ok is True


def test_tool_service_lists_workspaces_with_display_name(tmp_path):
    service = ToolService(
        registry=None,
        runtime=LocalDevRuntime(),
        workspace_base_root=tmp_path,
        policy=ToolPolicy(approval_required_for_command=False),
        enabled=True,
    )
    workspace = service.create_workspace(feature_name="tools", title="My Sandbox", actor="test")

    items = service.list_workspaces(feature_name="tools")

    assert items
    assert items[0]["workspace_id"] == workspace["workspace_id"]
    assert items[0]["display_name"] == "My Sandbox"


def test_tool_service_requires_preapproval_for_write_tools(tmp_path):
    service = ToolService(
        registry=None,
        runtime=LocalDevRuntime(),
        workspace_base_root=tmp_path,
        policy=ToolPolicy(approval_required_for_write=True, approval_required_for_command=False),
        enabled=True,
    )
    workspace = service.create_workspace(feature_name="tools", actor="test")

    try:
        asyncio.run(
            service.call_tool(
                workspace_id=workspace["workspace_id"],
                tool_name="write_file",
                arguments={"path": "notes.txt", "content": "hello"},
                actor="test",
            )
        )
    except ToolApprovalRequiredError as exc:
        assert "preapproval" in str(exc).lower()
    else:
        raise AssertionError("expected ToolApprovalRequiredError")


def test_tool_service_allows_write_tools_by_default_policy(tmp_path):
    service = ToolService(
        registry=None,
        runtime=LocalDevRuntime(),
        workspace_base_root=tmp_path,
        policy=ToolPolicy(approval_required_for_write=False, approval_required_for_command=False),
        enabled=True,
    )
    workspace = service.create_workspace(feature_name="tools", actor="test")

    result = asyncio.run(
        service.call_tool(
            workspace_id=workspace["workspace_id"],
            tool_name="write_file",
            arguments={"path": "notes.txt", "content": "hello"},
            actor="test",
        )
    )

    assert result.ok is True
    assert (tmp_path / workspace["workspace_id"] / "notes.txt").read_text(encoding="utf-8") == "hello"
