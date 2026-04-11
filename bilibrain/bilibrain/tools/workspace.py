from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from bilibrain.tools.errors import WorkspaceError


def ensure_workspace_exists(workspace_root: Path) -> Path:
    resolved_root = Path(workspace_root).expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    return resolved_root


def normalize_workspace_path(workspace_root: Path, relative_path: str | Path) -> Path:
    root = ensure_workspace_exists(workspace_root)
    raw_path = Path(str(relative_path or "."))
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("Path escapes workspace root.") from exc
    return candidate


def get_workspace_root(base_root: Path, workspace_id: str) -> Path:
    normalized_id = "".join(char for char in str(workspace_id or "").strip() if char.isalnum() or char in {"-", "_"})
    if not normalized_id:
        raise WorkspaceError("Workspace id is required.")
    root = ensure_workspace_exists(base_root)
    workspace_path = (root / normalized_id).resolve()
    try:
        workspace_path.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("Workspace path escapes root.") from exc
    workspace_path.mkdir(parents=True, exist_ok=True)
    return workspace_path


async def create_workspace_session(
    db: Any,
    *,
    feature_name: str,
    conversation_id: int | None = None,
    title: str | None = None,
    actor: str = "system",
) -> dict[str, Any]:
    workspace_id = uuid4().hex[:12]
    scope_key = f"{feature_name}:{conversation_id}" if conversation_id else feature_name
    return await db.create_tool_workspace(
        workspace_id=workspace_id,
        scope_key=scope_key,
        feature_name=feature_name,
        conversation_id=conversation_id,
        title=title,
        actor=actor,
    )
