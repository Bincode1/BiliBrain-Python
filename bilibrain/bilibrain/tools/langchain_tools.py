from __future__ import annotations

from typing import Any, Callable

from langchain_core.tools import tool

from bilibrain.tools.contracts import ToolApprovalMode


def _emit(callback: Callable[[str, dict[str, Any]], None] | None, event_type: str, payload: dict[str, Any]) -> None:
    if callback is None:
        return
    callback(event_type, payload)


def _summarize_tool_args(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if tool_name == "run_command":
        payload["command"] = str(arguments.get("command") or "")
        payload["cwd"] = str(arguments.get("cwd") or ".")
        return payload
    if tool_name == "web_search":
        return {
            "query": str(arguments.get("query") or ""),
            "max_results": int(arguments.get("max_results") or 5),
        }
    if tool_name == "browser_read_page":
        return {
            "url": str(arguments.get("url") or ""),
            "selector": str(arguments.get("selector") or "body"),
            "max_chars": int(arguments.get("max_chars") or 20000),
        }
    if tool_name in {"write_file", "append_file"}:
        content = str(arguments.get("content") or "")
        payload["path"] = str(arguments.get("path") or "")
        payload["content_length"] = len(content)
        payload["content_preview"] = (content[:120] + "...") if len(content) > 120 else content
        if "overwrite" in arguments:
            payload["overwrite"] = bool(arguments.get("overwrite"))
        return payload
    if tool_name == "make_dir":
        return {
            "path": str(arguments.get("path") or ""),
            "parents": bool(arguments.get("parents", True)),
            "exist_ok": bool(arguments.get("exist_ok", True)),
        }
    if tool_name in {"read_file", "list_dir"}:
        return {"path": str(arguments.get("path") or ".")}
    return dict(arguments or {})


def build_langchain_tools(
    tool_service,
    *,
    workspace_id: str,
    actor: str = "agent",
    approval_mode: ToolApprovalMode = ToolApprovalMode.AUTO,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
):
    async def _call(tool_name: str, arguments: dict[str, Any]) -> dict:
        summary = _summarize_tool_args(tool_name, arguments)
        _emit(
            event_callback,
            "tool",
            {
                "phase": "start",
                "name": tool_name,
                "workspace_id": workspace_id,
                "summary": summary,
            },
        )
        result = await tool_service.call_tool(
            workspace_id=workspace_id,
            tool_name=tool_name,
            arguments=arguments,
            actor=actor,
            approval_mode=approval_mode,
        )
        payload = result.model_dump()
        _emit(
            event_callback,
            "tool",
            {
                "phase": "finish",
                "name": tool_name,
                "workspace_id": workspace_id,
                "summary": summary,
                "ok": bool(payload.get("ok")),
                "error": payload.get("error"),
            },
        )
        return payload

    @tool("list_dir", description="List files and directories inside the current workspace.")
    async def list_dir(path: str = ".") -> dict:
        return await _call("list_dir", {"path": path})

    @tool("read_file", description="Read a text file inside the current workspace.")
    async def read_file(path: str, encoding: str = "utf-8") -> dict:
        return await _call("read_file", {"path": path, "encoding": encoding})

    @tool("write_file", description="Write a text file inside the current workspace.")
    async def write_file(path: str, content: str, encoding: str = "utf-8", overwrite: bool = True) -> dict:
        return await _call("write_file", {"path": path, "content": content, "encoding": encoding, "overwrite": overwrite})

    @tool("append_file", description="Append text to a file inside the current workspace.")
    async def append_file(path: str, content: str, encoding: str = "utf-8") -> dict:
        return await _call("append_file", {"path": path, "content": content, "encoding": encoding})

    @tool("make_dir", description="Create a directory inside the current workspace.")
    async def make_dir(path: str, parents: bool = True, exist_ok: bool = True) -> dict:
        return await _call("make_dir", {"path": path, "parents": parents, "exist_ok": exist_ok})

    @tool("run_command", description="Run a command in the current workspace through the configured runtime.")
    async def run_command(
        command: str,
        cwd: str = ".",
        timeout_seconds: int = 30,
    ) -> dict:
        return await _call(
            "run_command",
            {
                "command": command,
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
            },
        )

    @tool("web_search", description="Search the public web and return titles, URLs, and snippets.")
    async def web_search(query: str, max_results: int = 5) -> dict:
        return await _call(
            "web_search",
            {
                "query": query,
                "max_results": max_results,
            },
        )

    @tool(
        "browser_read_page",
        description="Open a public web page with agent-browser and return the final URL, page title, and extracted text.",
    )
    async def browser_read_page(
        url: str,
        selector: str = "body",
        timeout_seconds: int = 45,
        max_chars: int = 20000,
    ) -> dict:
        return await _call(
            "browser_read_page",
            {
                "url": url,
                "selector": selector,
                "timeout_seconds": timeout_seconds,
                "max_chars": max_chars,
            },
        )

    return [list_dir, read_file, write_file, append_file, make_dir, run_command, web_search, browser_read_page]
