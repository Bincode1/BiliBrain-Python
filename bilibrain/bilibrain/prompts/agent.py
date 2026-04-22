from __future__ import annotations

from bilibrain.prompts.loader import render_prompt_template


def build_unified_agent_system_prompt() -> str:
    return render_prompt_template("unified_agent_system.md")


def build_unified_agent_context_message(
    *,
    scope_description: str,
    workspace_id: str,
    available_skills: str,
    memory_text: str,
) -> str:
    lines: list[str] = [
        "## 当前范围",
        str(scope_description or "").strip() or "（当前范围未知）",
        "",
        f"当前 workspace_id: {str(workspace_id or '').strip() or 'default'}",
        "",
        "## 当前可用 skills 摘要",
        str(available_skills or "").strip() or "<available_skills />",
    ]
    normalized_memory = str(memory_text or "").strip()
    if normalized_memory:
        lines.extend(["", "## 对话记忆", normalized_memory])
    return "\n".join(lines).strip()
