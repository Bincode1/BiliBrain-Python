from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any

from bilibrain.tools.contracts import ToolCallResult, ToolCallTimer
from bilibrain.tools.errors import ToolError, WorkspaceError


def _normalize_markdown_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").rstrip("\n")


def _normalize_obsidian_note_path(raw_path: Any) -> str:
    normalized = str(raw_path or "").strip().replace("\\", "/")
    normalized = normalized.lstrip("/")
    if not normalized or normalized in {".", "./"}:
        raise WorkspaceError("Obsidian note path must point to a note inside the vault.")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        raise WorkspaceError("Obsidian note path cannot escape the vault root.")
    if not parts[-1].lower().endswith(".md"):
        parts[-1] = f"{parts[-1]}.md"
    return "/".join(parts)


def _resolve_obsidian_target(vault_root: Path, note_path: str) -> Path:
    candidate = (vault_root / Path(*note_path.split("/"))).resolve()
    resolved_root = vault_root.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise WorkspaceError("Resolved Obsidian note path escapes the vault root.") from exc
    return candidate


def _run_obsidian_cli(
    *,
    args: list[str],
    vault_name: str | None = None,
    timeout_seconds: int = 30,
) -> tuple[int, str, str]:
    executable = shutil.which("obsidian")
    if not executable:
        raise ToolError("Obsidian CLI executable was not found in PATH.")

    argv = [executable]
    normalized_vault_name = str(vault_name or "").strip()
    if normalized_vault_name:
        argv.append(f'vault={normalized_vault_name}')
    argv.extend(args)

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(int(timeout_seconds), 1),
        )
    except subprocess.TimeoutExpired as exc:
        return (
            124,
            str(exc.stdout or ""),
            str(exc.stderr or "Obsidian CLI command timed out."),
        )
    return (
        int(completed.returncode),
        str(completed.stdout or ""),
        str(completed.stderr or ""),
    )


def _resolve_obsidian_vault_root(
    *,
    vault_name: str | None = None,
    timeout_seconds: int = 15,
) -> Path:
    exit_code, stdout, stderr = _run_obsidian_cli(
        args=["vault", "info=path"],
        vault_name=vault_name,
        timeout_seconds=timeout_seconds,
    )
    if exit_code != 0:
        raise ToolError(
            stderr.strip() or stdout.strip() or "Failed to resolve Obsidian vault path."
        )
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise ToolError("Obsidian CLI returned an empty vault path.")
    return Path(lines[-1]).expanduser().resolve()


def _failure_result(
    *,
    tool_name: str,
    workspace_id: str,
    trace_id: str,
    timer: ToolCallTimer,
    message: str,
    payload: dict[str, Any] | None = None,
) -> ToolCallResult:
    return ToolCallResult(
        ok=False,
        tool_name=tool_name,
        workspace_id=workspace_id,
        trace_id=trace_id,
        payload=payload or {},
        error={"message": message},
        duration_ms=timer.elapsed_ms(),
    )


async def obsidian_write_note_tool(
    *,
    workspace_root: Path,
    arguments: dict[str, Any],
    workspace_id: str = "_local",
    trace_id: str = "local-obsidian-write-note",
) -> ToolCallResult:
    _ = workspace_root
    timer = ToolCallTimer()
    note_path = _normalize_obsidian_note_path(arguments.get("path", ""))
    content = str(arguments.get("content") or "")
    overwrite = bool(arguments.get("overwrite", True))
    vault_name = str(arguments.get("vault_name") or "").strip() or None
    timeout_seconds = max(int(arguments.get("timeout_seconds") or 30), 1)

    def _write_and_verify() -> ToolCallResult:
        try:
            vault_root = _resolve_obsidian_vault_root(
                vault_name=vault_name,
                timeout_seconds=min(timeout_seconds, 15),
            )
        except ToolError as exc:
            return _failure_result(
                tool_name="obsidian_write_note",
                workspace_id=workspace_id,
                trace_id=trace_id,
                timer=timer,
                message=str(exc),
            )

        target = _resolve_obsidian_target(vault_root, note_path)
        if target.exists() and not overwrite:
            return _failure_result(
                tool_name="obsidian_write_note",
                workspace_id=workspace_id,
                trace_id=trace_id,
                timer=timer,
                message=f"Obsidian note already exists: {note_path}",
                payload={"path": note_path, "absolute_path": str(target)},
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        file_exit, file_stdout, file_stderr = _run_obsidian_cli(
            args=["file", f"path={note_path}"],
            vault_name=vault_name,
            timeout_seconds=min(timeout_seconds, 15),
        )
        if file_exit != 0:
            return _failure_result(
                tool_name="obsidian_write_note",
                workspace_id=workspace_id,
                trace_id=trace_id,
                timer=timer,
                message=file_stderr.strip() or file_stdout.strip() or "Obsidian CLI could not resolve the written note.",
                payload={"path": note_path, "absolute_path": str(target)},
            )

        read_exit, read_stdout, read_stderr = _run_obsidian_cli(
            args=["read", f"path={note_path}"],
            vault_name=vault_name,
            timeout_seconds=timeout_seconds,
        )
        if read_exit != 0:
            return _failure_result(
                tool_name="obsidian_write_note",
                workspace_id=workspace_id,
                trace_id=trace_id,
                timer=timer,
                message=read_stderr.strip() or read_stdout.strip() or "Obsidian CLI could not read the written note.",
                payload={"path": note_path, "absolute_path": str(target)},
            )

        if _normalize_markdown_text(read_stdout) != _normalize_markdown_text(content):
            return _failure_result(
                tool_name="obsidian_write_note",
                workspace_id=workspace_id,
                trace_id=trace_id,
                timer=timer,
                message="Obsidian note verification failed: read-back content does not match the written content.",
                payload={
                    "path": note_path,
                    "absolute_path": str(target),
                    "written_length": len(_normalize_markdown_text(content)),
                    "read_back_length": len(_normalize_markdown_text(read_stdout)),
                },
            )

        return ToolCallResult(
            ok=True,
            tool_name="obsidian_write_note",
            workspace_id=workspace_id,
            trace_id=trace_id,
            payload={
                "path": note_path,
                "absolute_path": str(target),
                "vault_path": str(vault_root),
                "size": target.stat().st_size,
                "verified": True,
            },
            duration_ms=timer.elapsed_ms(),
        )

    return await asyncio.to_thread(_write_and_verify)


async def obsidian_read_note_tool(
    *,
    workspace_root: Path,
    arguments: dict[str, Any],
    workspace_id: str = "_local",
    trace_id: str = "local-obsidian-read-note",
) -> ToolCallResult:
    _ = workspace_root
    timer = ToolCallTimer()
    note_path = _normalize_obsidian_note_path(arguments.get("path", ""))
    vault_name = str(arguments.get("vault_name") or "").strip() or None
    timeout_seconds = max(int(arguments.get("timeout_seconds") or 15), 1)

    def _read_note() -> ToolCallResult:
        try:
            vault_root = _resolve_obsidian_vault_root(
                vault_name=vault_name,
                timeout_seconds=timeout_seconds,
            )
        except ToolError as exc:
            return _failure_result(
                tool_name="obsidian_read_note",
                workspace_id=workspace_id,
                trace_id=trace_id,
                timer=timer,
                message=str(exc),
            )

        target = _resolve_obsidian_target(vault_root, note_path)
        if not target.exists():
            return _failure_result(
                tool_name="obsidian_read_note",
                workspace_id=workspace_id,
                trace_id=trace_id,
                timer=timer,
                message=f"Obsidian note not found: {note_path}",
                payload={"path": note_path, "absolute_path": str(target)},
            )

        content = target.read_text(encoding="utf-8-sig")
        return ToolCallResult(
            ok=True,
            tool_name="obsidian_read_note",
            workspace_id=workspace_id,
            trace_id=trace_id,
            payload={
                "path": note_path,
                "absolute_path": str(target),
                "vault_path": str(vault_root),
                "content": content,
                "size": target.stat().st_size,
            },
            duration_ms=timer.elapsed_ms(),
        )

    return await asyncio.to_thread(_read_note)
