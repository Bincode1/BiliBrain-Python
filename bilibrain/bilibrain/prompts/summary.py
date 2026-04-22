from __future__ import annotations

from bilibrain.prompts.loader import render_prompt_template

SUMMARY_TEMPLATE_SYSTEM = "summary_system.md"
SUMMARY_TEMPLATE_FULL = "summary_full_user.md"
SUMMARY_TEMPLATE_WINDOW = "summary_window_user.md"
SUMMARY_TEMPLATE_REDUCE = "summary_reduce_user.md"


def _summary_system_message() -> tuple[str, str]:
    return ("system", render_prompt_template(SUMMARY_TEMPLATE_SYSTEM))


def build_summary_full_messages(
    *,
    video_title: str,
    transcript_text: str,
) -> list[tuple[str, str]]:
    return [
        _summary_system_message(),
        (
            "human",
            render_prompt_template(
                SUMMARY_TEMPLATE_FULL,
                video_title=str(video_title or "").strip(),
                transcript_text=str(transcript_text or "").strip(),
            ),
        ),
    ]


def build_summary_window_messages(
    *,
    video_title: str,
    transcript_text: str,
) -> list[tuple[str, str]]:
    return [
        _summary_system_message(),
        (
            "human",
            render_prompt_template(
                SUMMARY_TEMPLATE_WINDOW,
                video_title=str(video_title or "").strip(),
                transcript_text=str(transcript_text or "").strip(),
            ),
        ),
    ]


def build_summary_reduce_messages(
    *,
    video_title: str,
    window_summaries: list[str],
) -> list[tuple[str, str]]:
    payload = "\n\n".join(
        f"[局部摘要 {index}]\n{str(summary or '').strip()}"
        for index, summary in enumerate(window_summaries, start=1)
        if str(summary or "").strip()
    )
    requirements_block = "\n".join(
        [
            "1. 只依据局部摘要内容，不补充外部知识。",
            "2. 回答用中文。",
            "3. 输出结构固定为：一句话概括、核心要点、详细梳理。",
            "4. 核心要点控制在 4 到 8 条，尽量覆盖整个视频主要主题。",
            "5. 去掉重复信息，保留关键结论、方法、步骤和注意点。",
        ]
    )
    return [
        _summary_system_message(),
        (
            "human",
            render_prompt_template(
                SUMMARY_TEMPLATE_REDUCE,
                subject_block=f"视频标题：{str(video_title or '').strip()}",
                task_description="以下是同一个视频多个片段的局部摘要，请合并成一份最终摘要。",
                requirements_block=requirements_block,
                source_label="局部摘要",
                source_text=payload,
            ),
        ),
    ]


def build_summary_reduce_document_messages(
    *,
    query: str,
    summary_text: str,
) -> list[tuple[str, str]]:
    requirements_block = "\n".join(
        [
            "1. 只依据给定摘要，不补充外部知识。",
            "2. 回答用中文。",
            "3. 输出 4 到 8 条高信息密度要点。",
            "4. 优先保留共性主题、代表观点和明显差异。",
            "5. 不要写空话，不要附加编号解释。",
        ]
    )
    return [
        _summary_system_message(),
        (
            "human",
            render_prompt_template(
                SUMMARY_TEMPLATE_REDUCE,
                subject_block=f"用户问题：{str(query or '').strip()}",
                task_description="以下是同一范围内多个视频的摘要，请先做一轮中间压缩，供后续总汇总使用。",
                requirements_block=requirements_block,
                source_label="视频摘要",
                source_text=str(summary_text or "").strip(),
            ),
        ),
    ]
