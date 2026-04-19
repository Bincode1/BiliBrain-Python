from __future__ import annotations

from typing import Any

from bilibrain.services.common import estimate_text_tokens


DEFAULT_RECENT_TURNS = 5


def estimate_history_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for item in messages:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if not role or not content:
            continue
        total += estimate_text_tokens(f"{role}: {content}")
    return total


def split_recent_history(
    history: list[dict[str, Any]],
    *,
    keep_turns: int = DEFAULT_RECENT_TURNS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not history:
        return [], []

    safe_turns = max(int(keep_turns), 1)
    recent_reversed: list[dict[str, Any]] = []
    user_turns = 0

    for item in reversed(history):
        recent_reversed.append(item)
        if str(item.get("role") or "").strip().lower() == "user":
            user_turns += 1
            if user_turns >= safe_turns:
                break

    recent_history = list(reversed(recent_reversed))
    split_index = max(len(history) - len(recent_history), 0)
    return history[:split_index], recent_history


def format_history_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, item in enumerate(messages, start=1):
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        speaker = "用户" if role == "user" else "助手"
        lines.append(f"[{index}] {speaker}: {content}")
    return "\n".join(lines)
