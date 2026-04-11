import asyncio

import bilibrain.tools.web_search as web_search_module

from bilibrain.tools.langchain_tools import build_langchain_tools
from bilibrain.tools.policy import ToolPolicy
from bilibrain.tools.runtime.local_dev import LocalDevRuntime
from bilibrain.tools.service import ToolService


def test_langchain_tool_wrapper_invokes_underlying_tool_service(tmp_path):
    service = ToolService(
        runtime=LocalDevRuntime(),
        workspace_base_root=tmp_path,
        policy=ToolPolicy(approval_required_for_command=False),
        enabled=True,
    )
    workspace = service.create_workspace(feature_name="tools", actor="agent")
    tools = {item.name: item for item in build_langchain_tools(service, workspace_id=workspace["workspace_id"])}

    result = asyncio.run(tools["list_dir"].ainvoke({"path": "."}))

    assert result["tool_name"] == "list_dir"
    assert result["ok"] is True
    assert "write_file" in tools
    assert "web_search" in tools
    assert "browser_read_page" in tools


def test_langchain_tool_wrapper_emits_tool_events(tmp_path):
    events = []
    service = ToolService(
        runtime=LocalDevRuntime(),
        workspace_base_root=tmp_path,
        policy=ToolPolicy(approval_required_for_command=False),
        enabled=True,
    )
    workspace = service.create_workspace(feature_name="tools", actor="agent")
    tools = {
        item.name: item
        for item in build_langchain_tools(
            service,
            workspace_id=workspace["workspace_id"],
            event_callback=lambda event_type, payload: events.append((event_type, payload)),
        )
    }

    asyncio.run(tools["run_command"].ainvoke({"command": "python -V"}))

    assert events[0][0] == "tool"
    assert events[0][1]["phase"] == "start"
    assert events[0][1]["name"] == "run_command"
    assert events[1][0] == "tool"
    assert events[1][1]["phase"] == "finish"
    assert events[1][1]["name"] == "run_command"


def test_langchain_web_search_wrapper_invokes_tool_service(tmp_path, monkeypatch):
    async def fake_search(query: str, *, max_results: int = 5):
        return [
            {
                "rank": 1,
                "title": f"Result for {query}",
                "url": "https://example.com",
                "snippet": "demo snippet",
                "provider": "bing_rss",
            }
        ][:max_results]

    monkeypatch.setattr(web_search_module, "perform_web_search", fake_search)

    service = ToolService(
        runtime=LocalDevRuntime(),
        workspace_base_root=tmp_path,
        policy=ToolPolicy(approval_required_for_command=False),
        enabled=True,
    )
    workspace = service.create_workspace(feature_name="tools", actor="agent")
    tools = {item.name: item for item in build_langchain_tools(service, workspace_id=workspace["workspace_id"])}

    result = asyncio.run(tools["web_search"].ainvoke({"query": "tokyo travel", "max_results": 3}))

    assert result["tool_name"] == "web_search"
    assert result["ok"] is True
    assert result["payload"]["result_count"] == 1
    assert result["payload"]["results"][0]["title"] == "Result for tokyo travel"
