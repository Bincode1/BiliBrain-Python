from pathlib import Path

from bilibrain.tools.runtime.docker_models import DockerSandboxConfig
from bilibrain.tools.runtime.docker_sandbox import build_docker_run_command


def test_build_docker_run_command_includes_sandbox_flags(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    nested = root / "src"
    nested.mkdir()
    config = DockerSandboxConfig(image="python:3.13-alpine")

    argv = build_docker_run_command(
        docker_bin="docker",
        config=config,
        workspace_root=root,
        cwd=nested,
        command="python -V",
        env={"FOO": "bar"},
    )

    joined = " ".join(argv)
    assert "--read-only" in argv
    assert "--network" in argv
    assert "none" in argv
    assert "--mount" in argv
    assert "python:3.13-alpine" in argv
    assert "/bin/sh" in argv
    assert "-lc" in argv
    assert "python -V" in argv
    assert "--env" in argv
    assert "FOO=bar" in argv
    assert "/workspace/src" in joined
