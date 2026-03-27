from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from bilibrain.tools.runtime.contracts import BaseToolRuntime, RuntimeExecResult, RuntimeTimer
from bilibrain.tools.workspace import normalize_workspace_path


class LocalDevRuntime(BaseToolRuntime):
    def __init__(
        self,
        *,
        max_stdout_bytes: int = 65536,
        max_stderr_bytes: int = 65536,
    ) -> None:
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
        workspace_path = normalize_workspace_path(workspace_root, cwd)
        timer = RuntimeTimer()
        merged_env = os.environ.copy()
        merged_env.update({str(key): str(value) for key, value in (env or {}).items()})

        def _run() -> RuntimeExecResult:
            try:
                completed = subprocess.run(
                    str(command),
                    cwd=str(workspace_path),
                    env=merged_env,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=max(int(timeout_seconds), 1),
                )
                return RuntimeExecResult(
                    exit_code=int(completed.returncode),
                    stdout=_truncate_text(completed.stdout, self.max_stdout_bytes),
                    stderr=_truncate_text(completed.stderr, self.max_stderr_bytes),
                    timed_out=False,
                    duration_ms=timer.elapsed_ms(),
                    command=str(command),
                    cwd=str(workspace_path),
                )
            except subprocess.TimeoutExpired as exc:
                return RuntimeExecResult(
                    exit_code=124,
                    stdout=_truncate_text(exc.stdout or "", self.max_stdout_bytes),
                    stderr=_truncate_text(exc.stderr or "Command timed out.", self.max_stderr_bytes),
                    timed_out=True,
                    duration_ms=timer.elapsed_ms(),
                    command=str(command),
                    cwd=str(workspace_path),
                )

        return await asyncio.to_thread(_run)


def _truncate_text(payload: str, limit_bytes: int) -> str:
    text = str(payload or "")
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit_bytes:
        return text
    return encoded[:limit_bytes].decode("utf-8", errors="ignore") + "\n...[truncated]"
