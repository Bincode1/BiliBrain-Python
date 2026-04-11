from __future__ import annotations

from typing import Any, Callable


def _emit(callback: Callable[[str, dict[str, Any]], None] | None, event_type: str, payload: dict[str, Any]) -> None:
    if callback is None:
        return
    callback(event_type, payload)


def build_skill_langchain_tools(
    skill_service,
    *,
    session_id: str,
    actor: str = "agent",
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
):
    # Skills 由用户在 Skills 页面激活/停用，AI 不需要激活工具
    return []
