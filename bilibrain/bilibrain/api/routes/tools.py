from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from bilibrain.api.deps import get_runtime
from bilibrain.core.runtime import Runtime
from bilibrain.tools.contracts import ToolCallRequest, ToolWorkspaceCreateRequest


router = APIRouter()


@router.get("/api/tools")
async def list_tools(runtime: Runtime = Depends(get_runtime)) -> dict[str, Any]:
    return {
        "enabled": bool(runtime.tool_service and runtime.tool_service.enabled),
        "tools": runtime.tool_service.list_tools() if runtime.tool_service else [],
    }


@router.get("/api/tools/workspaces")
async def list_tool_workspaces(
    feature_name: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")
    return {
        "workspaces": await runtime.tool_service.list_workspaces(
            feature_name=feature_name, limit=limit
        ),
    }


@router.post("/api/tools/workspaces")
async def create_tool_workspace(
    payload: ToolWorkspaceCreateRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")
    return await runtime.tool_service.create_workspace(
        feature_name=payload.feature_name,
        conversation_id=payload.conversation_id,
        title=payload.title,
        actor=payload.actor,
    )


@router.get("/api/tools/workspaces/{workspace_id}")
async def get_tool_workspace(
    workspace_id: str, runtime: Runtime = Depends(get_runtime)
) -> dict[str, Any]:
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")
    return await runtime.tool_service.get_workspace(workspace_id)


@router.post("/api/tools/call")
async def call_tool(
    payload: ToolCallRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, Any]:
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")
    result = await runtime.tool_service.call_tool(
        workspace_id=payload.workspace_id,
        tool_name=payload.tool_name,
        arguments=payload.arguments,
        actor=payload.actor,
        approval_mode=payload.approval_mode,
        trace_id=payload.trace_id,
    )
    return result.model_dump()
