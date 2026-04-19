from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bilibrain.services.common import estimate_text_tokens
from bilibrain.services.runtime_state import read_runtime_state


WORKSPACE_QUERY_KEYWORDS = (
    "刚才",
    "上一步",
    "继续",
    "文件",
    "命令",
    "workspace",
    "写入",
    "运行",
    "报错",
)


@dataclass
class WorkspaceContextSelection:
    selected_keys: list[str]
    prompt_text: str
    token_estimate: int


def should_include_workspace_context(query: str) -> bool:
    lowered = str(query or "").lower()
    return any(keyword in lowered for keyword in WORKSPACE_QUERY_KEYWORDS)


def select_workspace_state_keys(runtime_state: dict[str, Any], *, query: str) -> list[str]:
    if not should_include_workspace_context(query):
        return []
    selected: list[str] = []
    if runtime_state.get("last_write_file"):
        selected.append("last_write_file")
    if runtime_state.get("last_run_command"):
        selected.append("last_run_command")
    pending = runtime_state.get("pending_approval")
    if isinstance(pending, dict) and pending.get("exists"):
        selected.append("pending_approval")
    if runtime_state.get("recent_file_reads"):
        selected.append("recent_file_reads")
    return selected


def format_workspace_state_for_prompt(
    runtime_state: dict[str, Any],
    *,
    selected_keys: list[str],
) -> str:
    lines: list[str] = []
    for key in selected_keys:
        value = runtime_state.get(key)
        if key == "last_write_file" and isinstance(value, dict):
            path = str(value.get("path") or "").strip()
            summary = str(value.get("summary") or "").strip()
            if summary:
                lines.append(f"[last_write_file] {summary}")
            elif path:
                lines.append(f"[last_write_file] 最近一次写入的文件是 {path}")
        elif key == "last_run_command" and isinstance(value, dict):
            summary = str(value.get("summary") or "").strip()
            if summary:
                lines.append(f"[last_run_command] {summary}")
        elif key == "pending_approval" and isinstance(value, dict) and value.get("exists"):
            action_name = str(value.get("action_name") or "").strip()
            lines.append(
                f"[pending_approval] 当前存在待审批动作{f'：{action_name}' if action_name else ''}"
            )
        elif key == "recent_file_reads":
            reads = list(value or [])
            if reads:
                path = str(reads[0].get("path") or "").strip()
                if path:
                    lines.append(f"[recent_file_reads] 最近读取过文件 {path}")
    return "\n".join(lines).strip()


async def select_workspace_context(runtime, *, query: str) -> WorkspaceContextSelection:
    runtime_state = await read_runtime_state(runtime)
    selected_keys = select_workspace_state_keys(runtime_state, query=query)
    prompt_text = format_workspace_state_for_prompt(
        runtime_state,
        selected_keys=selected_keys,
    )
    return WorkspaceContextSelection(
        selected_keys=selected_keys,
        prompt_text=prompt_text,
        token_estimate=estimate_text_tokens(prompt_text),
    )
