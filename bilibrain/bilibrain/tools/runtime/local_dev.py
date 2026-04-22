from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
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
        script_body: str | None = None,
        script_shell: str | None = None,
    ) -> RuntimeExecResult:
        workspace_path = normalize_workspace_path(workspace_root, cwd)
        timer = RuntimeTimer()
        merged_env = os.environ.copy()
        merged_env.update({str(key): str(value) for key, value in (env or {}).items()})

        def _run() -> RuntimeExecResult:
            try:
                if str(script_body or "").strip():
                    return _run_script(
                        workspace_path=workspace_path,
                        command=command,
                        timeout_seconds=timeout_seconds,
                        env=merged_env,
                        timer=timer,
                        script_body=str(script_body),
                        script_shell=str(script_shell or ""),
                        max_stdout_bytes=self.max_stdout_bytes,
                        max_stderr_bytes=self.max_stderr_bytes,
                    )
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


def _run_script(
    *,
    workspace_path: Path,
    command: str,
    timeout_seconds: int,
    env: dict[str, str],
    timer: RuntimeTimer,
    script_body: str,
    script_shell: str,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
) -> RuntimeExecResult:
    shell_name = script_shell.strip().lower() or "powershell"
    suffix, shell_command = _resolve_script_runner(shell_name)
    script_encoding = _resolve_script_encoding(shell_name)
    script_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=script_encoding,
            suffix=suffix,
            dir=str(workspace_path),
            delete=False,
        ) as handle:
            handle.write(script_body)
            script_path = handle.name
        completed = subprocess.run(
            [*shell_command, script_path],
            cwd=str(workspace_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=max(int(timeout_seconds), 1),
        )
        return RuntimeExecResult(
            exit_code=int(completed.returncode),
            stdout=_truncate_text(completed.stdout, max_stdout_bytes),
            stderr=_truncate_text(completed.stderr, max_stderr_bytes),
            timed_out=False,
            duration_ms=timer.elapsed_ms(),
            command=str(command),
            cwd=str(workspace_path),
        )
    except subprocess.TimeoutExpired as exc:
        return RuntimeExecResult(
            exit_code=124,
            stdout=_truncate_text(exc.stdout or "", max_stdout_bytes),
            stderr=_truncate_text(exc.stderr or "Command timed out.", max_stderr_bytes),
            timed_out=True,
            duration_ms=timer.elapsed_ms(),
            command=str(command),
            cwd=str(workspace_path),
        )
    finally:
        if script_path:
            try:
                Path(script_path).unlink(missing_ok=True)
            except OSError:
                pass


def _resolve_script_runner(shell_name: str) -> tuple[str, list[str]]:
    if shell_name in {"powershell", "pwsh"}:
        return ".ps1", ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    if shell_name in {"bash", "sh"}:
        return ".sh", [shell_name]
    raise ValueError(f"Unsupported script shell: {shell_name}")


def _resolve_script_encoding(shell_name: str) -> str:
    if shell_name in {"powershell", "pwsh"}:
        # Windows PowerShell 5.1 misreads UTF-8 without BOM for .ps1 files,
        # which garbles CJK content passed through script_body.
        return "utf-8-sig"
    return "utf-8"


def _truncate_text(payload: str, limit_bytes: int) -> str:
    text = str(payload or "")
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit_bytes:
        return text
    return encoded[:limit_bytes].decode("utf-8", errors="ignore") + "\n...[truncated]"
