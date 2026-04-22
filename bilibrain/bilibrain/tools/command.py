from __future__ import annotations

from pathlib import Path
from typing import Any

from bilibrain.tools.contracts import ToolCallResult, ToolCallTimer
from bilibrain.tools.runtime.contracts import BaseToolRuntime


async def run_command_tool(
    *,
    runtime: BaseToolRuntime,
    workspace_root: Path,
    arguments: dict[str, Any],
    workspace_id: str = "_local",
    trace_id: str = "local-run-command",
) -> ToolCallResult:
    timer = ToolCallTimer()
    command = str(arguments.get("command") or "").strip()
    cwd = str(arguments.get("cwd") or ".")
    timeout_seconds = max(int(arguments.get("timeout_seconds") or 30), 1)
    env = arguments.get("env") or {}
    script_body = str(arguments.get("script_body") or "") or None
    script_shell = str(arguments.get("script_shell") or "").strip() or None
    result = await runtime.exec(
        workspace_root=workspace_root,
        command=command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        env=env,
        script_body=script_body,
        script_shell=script_shell,
    )
    return ToolCallResult(
        ok=result.exit_code == 0 and not result.timed_out,
        tool_name="run_command",
        workspace_id=workspace_id,
        trace_id=trace_id,
        payload={
            "command": result.command,
            "cwd": result.cwd,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
            "duration_ms": result.duration_ms,
            "script_shell": script_shell,
            "used_script_body": bool(script_body),
        },
        duration_ms=timer.elapsed_ms(),
    )
