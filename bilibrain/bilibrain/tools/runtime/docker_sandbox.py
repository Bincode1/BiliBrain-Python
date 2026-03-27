from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from bilibrain.tools.runtime.contracts import BaseToolRuntime, RuntimeExecResult, RuntimeTimer
from bilibrain.tools.runtime.docker_models import DockerSandboxConfig
from bilibrain.tools.workspace import ensure_workspace_exists, normalize_workspace_path


class DockerSandboxRuntime(BaseToolRuntime):
    def __init__(
        self,
        *,
        config: DockerSandboxConfig | None = None,
        docker_bin: str = "docker",
        max_stdout_bytes: int = 65536,
        max_stderr_bytes: int = 65536,
    ) -> None:
        self.config = config or DockerSandboxConfig()
        self.docker_bin = str(docker_bin or "docker")
        self.max_stdout_bytes = max(int(max_stdout_bytes), 1024)
        self.max_stderr_bytes = max(int(max_stderr_bytes), 1024)

    async def exec(
        self,
        *,
        workspace_root: Path,
        command: str,
        cwd: str = ".",
        timeout_seconds: int = 30,
        env: dict[str, str] | None = None,
    ) -> RuntimeExecResult:
        workspace_path = ensure_workspace_exists(workspace_root)
        target_cwd = normalize_workspace_path(workspace_root, cwd)
        timer = RuntimeTimer()
        argv = build_docker_run_command(
            docker_bin=self.docker_bin,
            config=self.config,
            workspace_root=workspace_path,
            cwd=target_cwd,
            command=command,
            env=env or {},
        )

        def _run() -> RuntimeExecResult:
            try:
                completed = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    shell=False,
                    timeout=max(int(timeout_seconds), 1),
                )
                return RuntimeExecResult(
                    exit_code=int(completed.returncode),
                    stdout=_truncate_text(completed.stdout, self.max_stdout_bytes),
                    stderr=_truncate_text(completed.stderr, self.max_stderr_bytes),
                    timed_out=False,
                    duration_ms=timer.elapsed_ms(),
                    command=str(command),
                    cwd=str(target_cwd),
                )
            except subprocess.TimeoutExpired as exc:
                return RuntimeExecResult(
                    exit_code=124,
                    stdout=_truncate_text(exc.stdout or "", self.max_stdout_bytes),
                    stderr=_truncate_text(exc.stderr or "Command timed out.", self.max_stderr_bytes),
                    timed_out=True,
                    duration_ms=timer.elapsed_ms(),
                    command=str(command),
                    cwd=str(target_cwd),
                )

        return await asyncio.to_thread(_run)


def build_docker_run_command(
    *,
    docker_bin: str,
    config: DockerSandboxConfig,
    workspace_root: Path,
    cwd: Path,
    command: str,
    env: dict[str, str],
) -> list[str]:
    resolved_root = ensure_workspace_exists(workspace_root)
    resolved_cwd = cwd.resolve()
    relative_cwd = resolved_cwd.relative_to(resolved_root).as_posix() if resolved_cwd != resolved_root else ""
    container_workdir = config.workspace_mount_path.rstrip("/")
    if relative_cwd:
        container_workdir = f"{container_workdir}/{relative_cwd}"

    argv = [
        docker_bin,
        "run",
        "--rm",
        "--init",
        "--user",
        config.user,
        "--workdir",
        container_workdir,
        "--mount",
        f"type=bind,src={_docker_host_path(resolved_root)},dst={config.workspace_mount_path}",
        "--memory",
        config.normalized_memory_limit(),
        "--cpus",
        str(max(float(config.cpu_limit), 0.1)),
        "--pids-limit",
        str(max(int(config.pids_limit), 16)),
        "--tmpfs",
        config.normalized_tmpfs_mount(),
    ]
    if config.read_only_rootfs:
        argv.append("--read-only")
    if config.network_disabled:
        argv.extend(["--network", "none"])
    for key, value in sorted((env or {}).items()):
        argv.extend(["--env", f"{key}={value}"])
    argv.extend(
        [
            config.image,
            config.shell_executable,
            "-lc",
            str(command),
        ]
    )
    return argv


def _docker_host_path(path: Path) -> str:
    resolved = str(path.resolve())
    return resolved.replace("\\", "/") if os.name == "nt" else resolved


def _truncate_text(payload: str, limit_bytes: int) -> str:
    text = str(payload or "")
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit_bytes:
        return text
    return encoded[:limit_bytes].decode("utf-8", errors="ignore") + "\n...[truncated]"
