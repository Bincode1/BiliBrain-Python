from __future__ import annotations


class ToolError(RuntimeError):
    code = "tool_error"

    def to_payload(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class WorkspaceError(ToolError, ValueError):
    code = "workspace_error"


class PolicyError(ToolError):
    code = "policy_error"


class ToolApprovalRequiredError(ToolError):
    code = "approval_required"
