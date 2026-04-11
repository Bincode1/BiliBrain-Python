from types import SimpleNamespace

from bilibrain.tools.runtime.docker_sandbox import DockerSandboxRuntime
from bilibrain.tools.runtime.local_dev import LocalDevRuntime
from bilibrain.tools.service import create_tool_service


def _base_settings(tmp_path, runtime_name):
    return SimpleNamespace(
        tools_runtime=runtime_name,
        tools_workspace_root=tmp_path,
        tools_max_stdout_bytes=65536,
        tools_max_stderr_bytes=65536,
        tools_enabled=True,
        tools_default_timeout_seconds=30,
        tools_approval_required_for_write=False,
        tools_approval_required_for_command=False,
        tools_allowed_command_prefixes=(),
        tools_blocked_command_prefixes=(),
        tools_docker_image="python:3.13-alpine",
        tools_docker_user="65532:65532",
        tools_docker_workspace_mount_path="/workspace",
        tools_docker_shell="/bin/sh",
        tools_docker_read_only_rootfs=True,
        tools_docker_network_disabled=True,
        tools_docker_memory_limit_mb=512,
        tools_docker_cpu_limit=1.0,
        tools_docker_pids_limit=128,
        tools_docker_tmpfs_size_mb=64,
        tools_docker_bin="docker",
    )


def test_create_tool_service_uses_local_runtime_when_configured(tmp_path):
    service = create_tool_service(_base_settings(tmp_path, "local_dev"), db=None)
    assert isinstance(service.runtime, LocalDevRuntime)


def test_create_tool_service_uses_docker_runtime_when_configured(tmp_path):
    service = create_tool_service(_base_settings(tmp_path, "docker_sandbox"), db=None)
    assert isinstance(service.runtime, DockerSandboxRuntime)
