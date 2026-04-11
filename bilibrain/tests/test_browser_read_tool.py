import asyncio
from pathlib import Path

import pytest

import bilibrain.tools.browser_read as browser_read_module
from bilibrain.tools.runtime.contracts import RuntimeExecResult


class _FakeRuntime:
    def __init__(self):
        self.commands: list[str] = []

    async def exec(
        self,
        *,
        workspace_root: Path,
        command: str,
        cwd: str = ".",
        timeout_seconds: int = 30,
        env: dict[str, str] | None = None,
    ) -> RuntimeExecResult:
        self.commands.append(command)
        if " get title" in command:
            return RuntimeExecResult(
                exit_code=0,
                stdout="Example Domain\n",
                stderr="",
                timed_out=False,
                duration_ms=1.0,
                command=command,
                cwd=str(workspace_root),
            )
        if " get url" in command:
            return RuntimeExecResult(
                exit_code=0,
                stdout="https://example.com/final\n",
                stderr="",
                timed_out=False,
                duration_ms=1.0,
                command=command,
                cwd=str(workspace_root),
            )
        if " get text body" in command:
            return RuntimeExecResult(
                exit_code=0,
                stdout="Example page body text.\nSecond line.\n",
                stderr="",
                timed_out=False,
                duration_ms=1.0,
                command=command,
                cwd=str(workspace_root),
            )
        return RuntimeExecResult(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            duration_ms=1.0,
            command=command,
            cwd=str(workspace_root),
        )


class _FailingRuntime(_FakeRuntime):
    async def exec(
        self,
        *,
        workspace_root: Path,
        command: str,
        cwd: str = ".",
        timeout_seconds: int = 30,
        env: dict[str, str] | None = None,
    ) -> RuntimeExecResult:
        self.commands.append(command)
        if " open " in command:
            return RuntimeExecResult(
                exit_code=1,
                stdout="",
                stderr="browser executable missing",
                timed_out=False,
                duration_ms=1.0,
                command=command,
                cwd=str(workspace_root),
            )
        return RuntimeExecResult(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            duration_ms=1.0,
            command=command,
            cwd=str(workspace_root),
        )


def test_browser_read_page_tool_returns_structured_payload(tmp_path):
    runtime = _FakeRuntime()

    result = asyncio.run(
        browser_read_module.browser_read_page_tool(
            runtime=runtime,
            workspace_root=tmp_path,
            arguments={"url": "https://example.com/article", "max_chars": 5000},
            workspace_id="ws-test",
            trace_id="trace-test",
        )
    )

    assert result.ok is True
    assert result.tool_name == "browser_read_page"
    assert result.payload["url"] == "https://example.com/article"
    assert result.payload["final_url"] == "https://example.com/final"
    assert result.payload["title"] == "Example Domain"
    assert result.payload["text"] == "Example page body text.\nSecond line."
    assert result.payload["provider"] == "agent_browser"
    assert any("npx agent-browser" in command for command in runtime.commands)
    assert any(" get text body" in command for command in runtime.commands)
    assert runtime.commands[-1].endswith("close")


def test_browser_read_page_tool_rejects_invalid_url(tmp_path):
    runtime = _FakeRuntime()

    with pytest.raises(RuntimeError, match="valid http or https URL"):
        asyncio.run(
            browser_read_module.browser_read_page_tool(
                runtime=runtime,
                workspace_root=tmp_path,
                arguments={"url": "file:///tmp/secret.txt"},
                workspace_id="ws-test",
                trace_id="trace-test",
            )
        )


def test_browser_read_page_tool_surfaces_install_hint_on_failure(tmp_path):
    runtime = _FailingRuntime()

    with pytest.raises(RuntimeError, match="agent-browser install"):
        asyncio.run(
            browser_read_module.browser_read_page_tool(
                runtime=runtime,
                workspace_root=tmp_path,
                arguments={"url": "https://example.com/article"},
                workspace_id="ws-test",
                trace_id="trace-test",
            )
        )
