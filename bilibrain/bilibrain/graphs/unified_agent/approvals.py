from __future__ import annotations

from typing import Any

from bilibrain.tools.policy import evaluate_command_request


def build_approval_request(
    runtime,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_call_id: str,
) -> dict[str, Any]:
    action: dict[str, Any] = {
        "name": tool_name,
        "args": tool_args,
        "id": tool_call_id,
    }
    if tool_name == "obsidian_write_note":
        target_path = str((tool_args or {}).get("path") or "").strip()
        action["description"] = (
            f"将当前整理结果写入 Obsidian 笔记 `{target_path}` 并做读回校验。"
            if target_path
            else "将当前整理结果写入 Obsidian 笔记并做读回校验。"
        )
    elif tool_name in {"write_file", "append_file", "make_dir"}:
        target_path = str((tool_args or {}).get("path") or "").strip()
        action["description"] = (
            f"对路径 `{target_path}` 执行 {tool_name}。"
            if target_path
            else f"执行 {tool_name}。"
        )
    tool_policy = getattr(getattr(runtime, "tool_service", None), "policy", None)
    if tool_name == "run_command" and tool_policy is not None:
        decision = evaluate_command_request(
            tool_policy,
            str((tool_args or {}).get("command") or ""),
        )
        action["policy_allowed"] = bool(decision.allowed)
        action["policy_requires_approval"] = bool(decision.requires_approval)
        action["policy_reason"] = decision.reason
        action["policy_blocked"] = not bool(decision.allowed)
    else:
        action["policy_allowed"] = True
        action["policy_requires_approval"] = False
        action["policy_reason"] = ""
        action["policy_blocked"] = False
    return {
        "interrupt_id": tool_call_id,
        "action_requests": [action],
        "review_configs": [],
    }


def build_skill_approval_request(
    runtime,
    *,
    skill_name: str,
    tool_call_id: str,
    session_id: str,
    actor: str,
) -> dict[str, Any]:
    skill_service = runtime.skill_service
    if skill_service is None:
        raise RuntimeError("Skill service is not available.")
    decision = skill_service.evaluate_skill_access(
        name=skill_name,
        session_id=session_id,
        actor=actor,
    )
    skill_detail = skill_service.get_skill(name=skill_name)
    return {
        "interrupt_id": tool_call_id,
        "action_requests": [
            {
                "name": "skill",
                "args": {"name": skill_name},
                "id": tool_call_id,
                "description": f"技能 '{skill_name}' 需要审批后才能加载完整 SKILL.md。",
                "summary": {
                    "skill_name": skill_name,
                    "description": skill_detail.get("description") or "",
                    "resource_count": len(skill_detail.get("resources") or []),
                    "allowed_tools": skill_detail.get("allowed_tools") or [],
                    "access": decision.action.value,
                },
                "policy_allowed": True,
                "policy_requires_approval": bool(decision.requires_approval),
                "policy_reason": decision.reason,
                "policy_blocked": False,
            }
        ],
        "review_configs": [
            {
                "action_name": "skill",
                "allowed_decisions": ["approve", "edit", "reject"],
            }
        ],
    }
