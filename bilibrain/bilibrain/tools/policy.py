from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class ToolPolicy:
    allowed_command_prefixes: list[list[str]] = field(default_factory=list)
    blocked_command_prefixes: list[list[str]] = field(default_factory=list)
    default_timeout_seconds: int = 30
    approval_required_for_write: bool = False
    approval_required_for_command: bool = False


@dataclass(frozen=True)
class ToolPolicyDecision:
    allowed: bool
    requires_approval: bool
    reason: str


def _normalize_prefixes(prefixes: Iterable[Iterable[str]]) -> list[list[str]]:
    normalized: list[list[str]] = []
    for prefix in prefixes:
        parts = [str(part or "").strip() for part in prefix if str(part or "").strip()]
        if parts:
            normalized.append(parts)
    return normalized


def _command_parts(command: str) -> list[str]:
    try:
        return shlex.split(str(command or ""), posix=False)
    except ValueError:
        return str(command or "").split()


def _starts_with(parts: list[str], prefix: list[str]) -> bool:
    if not prefix or len(parts) < len(prefix):
        return False
    return parts[: len(prefix)] == prefix


def evaluate_command_request(policy: ToolPolicy, command: str) -> ToolPolicyDecision:
    parts = _command_parts(command)
    if not parts:
        return ToolPolicyDecision(allowed=False, requires_approval=False, reason="Empty command is not allowed.")

    blocked_prefixes = _normalize_prefixes(policy.blocked_command_prefixes)
    for prefix in blocked_prefixes:
        if _starts_with(parts, prefix):
            return ToolPolicyDecision(
                allowed=False,
                requires_approval=False,
                reason=f"Blocked command prefix: {' '.join(prefix)}",
            )

    allowed_prefixes = _normalize_prefixes(policy.allowed_command_prefixes)
    if allowed_prefixes and not any(_starts_with(parts, prefix) for prefix in allowed_prefixes):
        return ToolPolicyDecision(
            allowed=False,
            requires_approval=False,
            reason="Command prefix is not on the allowlist.",
        )

    return ToolPolicyDecision(
        allowed=True,
        requires_approval=bool(policy.approval_required_for_command),
        reason="Command allowed by policy.",
    )


def build_tool_policy(settings) -> ToolPolicy:
    return ToolPolicy(
        allowed_command_prefixes=[list(prefix) for prefix in getattr(settings, "tools_allowed_command_prefixes", ())],
        blocked_command_prefixes=[list(prefix) for prefix in getattr(settings, "tools_blocked_command_prefixes", ())],
        default_timeout_seconds=max(int(getattr(settings, "tools_default_timeout_seconds", 30) or 30), 1),
        approval_required_for_write=bool(getattr(settings, "tools_approval_required_for_write", False)),
        approval_required_for_command=bool(getattr(settings, "tools_approval_required_for_command", False)),
    )
