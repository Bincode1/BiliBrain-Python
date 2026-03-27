from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from time import perf_counter
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ToolCapability(StrEnum):
    FILESYSTEM_READ = "filesystem_read"
    FILESYSTEM_WRITE = "filesystem_write"
    COMMAND_EXECUTE = "command_execute"
    NETWORK_ACCESS = "network_access"
    EXTERNAL_NOTIFY = "external_notify"


class ToolApprovalMode(StrEnum):
    AUTO = "auto"
    REQUIRE_APPROVAL = "require_approval"
    PREAPPROVED = "preapproved"


class ToolCallRequest(BaseModel):
    workspace_id: str = Field(..., min_length=1, max_length=128)
    tool_name: str = Field(..., min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(default="system", min_length=1, max_length=64)
    approval_mode: ToolApprovalMode = Field(default=ToolApprovalMode.AUTO)
    trace_id: str = Field(default_factory=lambda: uuid4().hex)


class ToolWorkspaceCreateRequest(BaseModel):
    feature_name: str = Field(..., min_length=1, max_length=64)
    conversation_id: int | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, max_length=255)
    actor: str = Field(default="system", min_length=1, max_length=64)


class ToolCallResult(BaseModel):
    ok: bool
    tool_name: str = Field(..., min_length=1, max_length=64)
    workspace_id: str = Field(..., min_length=1, max_length=128)
    trace_id: str = Field(..., min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    duration_ms: float = 0.0


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    capabilities: tuple[ToolCapability, ...] = field(default_factory=tuple)
    approval_mode: ToolApprovalMode = ToolApprovalMode.AUTO
    enabled: bool = True


@dataclass(frozen=True)
class ToolExecutionContext:
    workspace_id: str
    actor: str
    trace_id: str
    approval_mode: ToolApprovalMode = ToolApprovalMode.AUTO
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCallTimer:
    started_at: float = field(default_factory=perf_counter)

    def elapsed_ms(self) -> float:
        return round((perf_counter() - self.started_at) * 1000, 3)
