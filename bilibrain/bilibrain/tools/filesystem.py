from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from bilibrain.tools.contracts import ToolCallResult, ToolCallTimer
from bilibrain.tools.errors import WorkspaceError
from bilibrain.tools.workspace import ensure_workspace_exists, normalize_workspace_path


def _ensure_file_target(workspace_root: Path, raw_path: Any) -> Path:
    normalized_input = str(raw_path or "").strip()
    if not normalized_input or normalized_input in {".", "./", ".\\"}:
        raise WorkspaceError("File path must point to a file inside the workspace, not the workspace root.")
    target = normalize_workspace_path(workspace_root, normalized_input)
    if target.exists() and target.is_dir():
        raise WorkspaceError("Target path points to a directory, not a file.")
    return target


async def list_dir_tool(
    *,
    workspace_root: Path,
    arguments: dict[str, Any],
    workspace_id: str = "_local",
    trace_id: str = "local-list-dir",
) -> ToolCallResult:
    timer = ToolCallTimer()
    target = normalize_workspace_path(workspace_root, arguments.get("path", "."))

    def _list() -> dict[str, Any]:
        items = []
        for entry in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            items.append(
                {
                    "name": entry.name,
                    "path": str(entry.relative_to(ensure_workspace_exists(workspace_root))).replace("\\", "/"),
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else None,
                }
            )
        return {"path": str(target), "items": items}

    payload = await asyncio.to_thread(_list)
    return ToolCallResult(
        ok=True,
        tool_name="list_dir",
        workspace_id=workspace_id,
        trace_id=trace_id,
        payload=payload,
        duration_ms=timer.elapsed_ms(),
    )


async def read_file_tool(
    *,
    workspace_root: Path,
    arguments: dict[str, Any],
    workspace_id: str = "_local",
    trace_id: str = "local-read-file",
) -> ToolCallResult:
    timer = ToolCallTimer()
    target = _ensure_file_target(workspace_root, arguments.get("path", ""))
    encoding = str(arguments.get("encoding") or "utf-8")

    def _read() -> dict[str, Any]:
        content = target.read_text(encoding=encoding)
        relative_path = str(target.relative_to(ensure_workspace_exists(workspace_root))).replace("\\", "/")
        return {
            "path": relative_path,
            "content": content,
            "encoding": encoding,
            "size": target.stat().st_size,
        }

    payload = await asyncio.to_thread(_read)
    return ToolCallResult(
        ok=True,
        tool_name="read_file",
        workspace_id=workspace_id,
        trace_id=trace_id,
        payload=payload,
        duration_ms=timer.elapsed_ms(),
    )


async def write_file_tool(
    *,
    workspace_root: Path,
    arguments: dict[str, Any],
    workspace_id: str = "_local",
    trace_id: str = "local-write-file",
) -> ToolCallResult:
    timer = ToolCallTimer()
    target = _ensure_file_target(workspace_root, arguments.get("path", ""))
    encoding = str(arguments.get("encoding") or "utf-8")
    content = str(arguments.get("content") or "")
    overwrite = bool(arguments.get("overwrite", True))

    def _write() -> dict[str, Any]:
        if target.exists() and not overwrite:
            raise FileExistsError(f"File already exists: {target.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)
        relative_path = str(target.relative_to(ensure_workspace_exists(workspace_root))).replace("\\", "/")
        return {
            "path": relative_path,
            "encoding": encoding,
            "size": target.stat().st_size,
            "written": True,
        }

    payload = await asyncio.to_thread(_write)
    return ToolCallResult(
        ok=True,
        tool_name="write_file",
        workspace_id=workspace_id,
        trace_id=trace_id,
        payload=payload,
        duration_ms=timer.elapsed_ms(),
    )


async def append_file_tool(
    *,
    workspace_root: Path,
    arguments: dict[str, Any],
    workspace_id: str = "_local",
    trace_id: str = "local-append-file",
) -> ToolCallResult:
    timer = ToolCallTimer()
    target = _ensure_file_target(workspace_root, arguments.get("path", ""))
    encoding = str(arguments.get("encoding") or "utf-8")
    content = str(arguments.get("content") or "")

    def _append() -> dict[str, Any]:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding=encoding) as handle:
            handle.write(content)
        relative_path = str(target.relative_to(ensure_workspace_exists(workspace_root))).replace("\\", "/")
        return {
            "path": relative_path,
            "encoding": encoding,
            "size": target.stat().st_size,
            "appended": True,
        }

    payload = await asyncio.to_thread(_append)
    return ToolCallResult(
        ok=True,
        tool_name="append_file",
        workspace_id=workspace_id,
        trace_id=trace_id,
        payload=payload,
        duration_ms=timer.elapsed_ms(),
    )


async def make_dir_tool(
    *,
    workspace_root: Path,
    arguments: dict[str, Any],
    workspace_id: str = "_local",
    trace_id: str = "local-make-dir",
) -> ToolCallResult:
    timer = ToolCallTimer()
    target = normalize_workspace_path(workspace_root, arguments.get("path", ""))

    def _mkdir() -> dict[str, Any]:
        target.mkdir(parents=bool(arguments.get("parents", True)), exist_ok=bool(arguments.get("exist_ok", True)))
        relative_path = str(target.relative_to(ensure_workspace_exists(workspace_root))).replace("\\", "/")
        return {
            "path": relative_path,
            "created": True,
        }

    payload = await asyncio.to_thread(_mkdir)
    return ToolCallResult(
        ok=True,
        tool_name="make_dir",
        workspace_id=workspace_id,
        trace_id=trace_id,
        payload=payload,
        duration_ms=timer.elapsed_ms(),
    )
