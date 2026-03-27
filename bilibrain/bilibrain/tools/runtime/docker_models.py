from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DockerSandboxConfig:
    image: str = "python:3.13-alpine"
    user: str = "65532:65532"
    workspace_mount_path: str = "/workspace"
    shell_executable: str = "/bin/sh"
    read_only_rootfs: bool = True
    network_disabled: bool = True
    memory_limit_mb: int = 512
    cpu_limit: float = 1.0
    pids_limit: int = 128
    tmpfs_size_mb: int = 64

    def normalized_memory_limit(self) -> str:
        return f"{max(int(self.memory_limit_mb), 64)}m"

    def normalized_tmpfs_mount(self) -> str:
        return f"/tmp:rw,noexec,nosuid,size={max(int(self.tmpfs_size_mb), 16)}m"
