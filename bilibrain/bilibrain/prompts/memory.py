from __future__ import annotations

from bilibrain.prompts.loader import render_prompt_template

MEMORY_TEMPLATE = "memory_compact.md"


def build_memory_compact_messages(
    *,
    existing_memory_text: str | None,
    history_transcript: str,
) -> list[tuple[str, str]]:
    return [
        (
            "system",
            render_prompt_template(
                MEMORY_TEMPLATE,
                existing_memory_text=str(existing_memory_text or "").strip() or "（暂无已有记忆）",
                history_transcript=str(history_transcript or "").strip() or "（暂无新增片段）",
            ),
        ),
    ]
