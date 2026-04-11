import asyncio

from bilibrain.tools.command import run_command_tool
from bilibrain.tools.runtime.local_dev import LocalDevRuntime


def test_run_command_tool_uses_runtime_and_returns_structured_payload(tmp_path):
    runtime = LocalDevRuntime()

    result = asyncio.run(
        run_command_tool(
            runtime=runtime,
            workspace_root=tmp_path,
            arguments={"command": "python -c \"print('hello')\""},
        )
    )

    assert result.ok is True
    assert result.payload["exit_code"] == 0
    assert "hello" in result.payload["stdout"]
