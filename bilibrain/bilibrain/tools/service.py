from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from bilibrain.tools.contracts import (
    ToolApprovalMode,
    ToolCallRequest,
    ToolCallResult,
    ToolCallTimer,
)
from bilibrain.tools.errors import PolicyError, ToolApprovalRequiredError, WorkspaceError
from bilibrain.tools.policy import ToolPolicy, ToolPolicyDecision, build_tool_policy, evaluate_command_request
from bilibrain.tools.registry import ToolRegistryItem, build_default_tool_registry
from bilibrain.tools.workspace import create_workspace_session, get_workspace_root


class ToolService:
    def __init__(
        self,
        *,
        workspace_base_root: Path,
        runtime=None,
        registry: dict[str, ToolRegistryItem] | None = None,
        policy: ToolPolicy | None = None,
        db: Any | None = None,
        enabled: bool = True,
    ) -> None:
        self.workspace_base_root = Path(workspace_base_root)
        self.runtime = runtime
        self.registry = registry or build_default_tool_registry()
        self.policy = policy or ToolPolicy()
        self.db = db
        self.enabled = bool(enabled)
        self._workspace_cache: dict[str, dict[str, Any]] = {}

    def list_tools(self) -> list[dict[str, Any]]:
        tools = []
        for item in self.registry.values():
            definition = item.definition
            tools.append(
                {
                    "name": definition.name,
                    "description": definition.description,
                    "capabilities": [cap.value for cap in definition.capabilities],
                    "approval_mode": definition.approval_mode.value,
                    "enabled": definition.enabled,
                    "runtime_required": item.runtime_required,
                }
            )
        return tools

    def list_workspaces(self, *, feature_name: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if self.db is not None:
            rows = self.db.list_tool_workspaces(feature_name=feature_name, limit=limit)
        else:
            rows = list(self._workspace_cache.values())
            if feature_name:
                rows = [row for row in rows if row.get("feature_name") == feature_name]
            rows = list(reversed(rows))[: max(int(limit or 100), 1)]

        result = []
        for row in rows:
            workspace_root = get_workspace_root(self.workspace_base_root, row["workspace_id"])
            title = str(row.get("title") or "").strip()
            feature = str(row.get("feature_name") or "workspace")
            short_id = str(row["workspace_id"])[:8]
            display_name = title or f"{feature}:{short_id}"
            result.append(
                {
                    **row,
                    "root_path": str(workspace_root),
                    "display_name": display_name,
                }
            )
        return result

    def create_workspace(
        self,
        *,
        feature_name: str,
        conversation_id: int | None = None,
        title: str | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        if self.db is not None:
            row = create_workspace_session(
                self.db,
                feature_name=feature_name,
                conversation_id=conversation_id,
                title=title,
                actor=actor,
            )
        else:
            workspace_id = f"{feature_name}-{len(self._workspace_cache) + 1}"
            row = {
                "workspace_id": workspace_id,
                "scope_key": f"{feature_name}:{conversation_id}" if conversation_id else feature_name,
                "feature_name": feature_name,
                "conversation_id": conversation_id,
                "title": title or "",
                "actor": actor,
            }
            self._workspace_cache[workspace_id] = row
        workspace_root = get_workspace_root(self.workspace_base_root, row["workspace_id"])
        return {
            **row,
            "root_path": str(workspace_root),
        }

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        workspace = self.db.get_tool_workspace(workspace_id) if self.db is not None else self._workspace_cache.get(workspace_id)
        if not workspace:
            raise WorkspaceError("Workspace does not exist.")
        workspace_root = get_workspace_root(self.workspace_base_root, workspace_id)
        return {
            **workspace,
            "root_path": str(workspace_root),
            "display_name": str(workspace.get("title") or "").strip() or f"{workspace.get('feature_name') or 'workspace'}:{workspace_id[:8]}",
        }

    async def call_tool(
        self,
        *,
        workspace_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        actor: str,
        approval_mode: ToolApprovalMode = ToolApprovalMode.AUTO,
        trace_id: str | None = None,
    ) -> ToolCallResult:
        if not self.enabled:
            raise RuntimeError("Tools are disabled.")

        timer = ToolCallTimer()
        resolved_trace_id = str(trace_id or "").strip() or uuid4().hex
        request = ToolCallRequest(
            workspace_id=workspace_id,
            tool_name=tool_name,
            arguments=arguments,
            actor=actor,
            approval_mode=approval_mode,
            trace_id=resolved_trace_id,
        )
        item = self.registry.get(request.tool_name)
        if item is None or not item.definition.enabled:
            raise RuntimeError(f"Unknown tool: {request.tool_name}")

        workspace = self.get_workspace(request.workspace_id)
        workspace_root = Path(workspace["root_path"])

        if self.db is not None:
            self.db.log_tool_call(
                trace_id=request.trace_id,
                workspace_id=request.workspace_id,
                tool_name=request.tool_name,
                actor=request.actor,
                approval_mode=request.approval_mode.value,
                status="started",
                arguments=request.arguments,
            )

        decision = self._evaluate_request(item, request)
        if not decision.allowed:
            raise PolicyError(decision.reason)
        if decision.requires_approval and request.approval_mode != ToolApprovalMode.PREAPPROVED:
            raise ToolApprovalRequiredError(decision.reason)

        kwargs = {
            "workspace_root": workspace_root,
            "arguments": request.arguments,
            "workspace_id": request.workspace_id,
            "trace_id": request.trace_id,
        }
        if item.runtime_required:
            if self.runtime is None:
                raise RuntimeError("Runtime is not configured for this tool.")
            kwargs["runtime"] = self.runtime

        result = await item.handler(**kwargs)
        final_result = result.model_copy(update={"duration_ms": timer.elapsed_ms()})

        if self.db is not None:
            self.db.log_tool_call(
                trace_id=request.trace_id,
                workspace_id=request.workspace_id,
                tool_name=request.tool_name,
                actor=request.actor,
                approval_mode=request.approval_mode.value,
                status="finished" if final_result.ok else "failed",
                arguments=request.arguments,
                result=final_result.payload,
                error=final_result.error,
                duration_ms=final_result.duration_ms,
            )
        return final_result

    def _evaluate_request(self, item: ToolRegistryItem, request: ToolCallRequest) -> ToolPolicyDecision:
        capabilities = set(item.definition.capabilities)
        if any(cap.value == "filesystem_write" for cap in capabilities):
            return ToolPolicyDecision(
                allowed=True,
                requires_approval=bool(self.policy.approval_required_for_write),
                reason="Write tool requires preapproval under the current policy.",
            )
        if request.tool_name != "run_command":
            return ToolPolicyDecision(allowed=True, requires_approval=False, reason="Tool allowed.")
        return evaluate_command_request(self.policy, str(request.arguments.get("command") or ""))


def create_tool_service(settings, db) -> ToolService:
    from bilibrain.tools.runtime.docker_models import DockerSandboxConfig
    from bilibrain.tools.runtime.docker_sandbox import DockerSandboxRuntime
    from bilibrain.tools.runtime.local_dev import LocalDevRuntime

    runtime = None
    runtime_name = str(settings.tools_runtime or "").strip().lower()
    if runtime_name == "local_dev":
        runtime = LocalDevRuntime(
            max_stdout_bytes=settings.tools_max_stdout_bytes,
            max_stderr_bytes=settings.tools_max_stderr_bytes,
        )
    elif runtime_name == "docker_sandbox":
        runtime = DockerSandboxRuntime(
            config=DockerSandboxConfig(
                image=settings.tools_docker_image,
                user=settings.tools_docker_user,
                workspace_mount_path=settings.tools_docker_workspace_mount_path,
                shell_executable=settings.tools_docker_shell,
                read_only_rootfs=settings.tools_docker_read_only_rootfs,
                network_disabled=settings.tools_docker_network_disabled,
                memory_limit_mb=settings.tools_docker_memory_limit_mb,
                cpu_limit=settings.tools_docker_cpu_limit,
                pids_limit=settings.tools_docker_pids_limit,
                tmpfs_size_mb=settings.tools_docker_tmpfs_size_mb,
            ),
            docker_bin=settings.tools_docker_bin,
            max_stdout_bytes=settings.tools_max_stdout_bytes,
            max_stderr_bytes=settings.tools_max_stderr_bytes,
        )

    return ToolService(
        workspace_base_root=settings.tools_workspace_root,
        runtime=runtime,
        policy=build_tool_policy(settings),
        db=db,
        enabled=bool(settings.tools_enabled),
    )
