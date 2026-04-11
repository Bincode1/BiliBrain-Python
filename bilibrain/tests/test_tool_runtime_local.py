import asyncio

from bilibrain.tools.runtime.local_dev import LocalDevRuntime


def test_local_runtime_exec_returns_exit_code_and_output(tmp_path):
    runtime = LocalDevRuntime()

    result = asyncio.run(
        runtime.exec(
            workspace_root=tmp_path,
            command="python -c \"print('ok')\"",
            cwd=".",
            timeout_seconds=10,
            env={},
        )
    )

    assert result.exit_code == 0
    assert "ok" in result.stdout
