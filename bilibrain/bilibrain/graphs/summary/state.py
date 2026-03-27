from __future__ import annotations

from typing import Any, TypedDict


class SummaryState(TypedDict, total=False):
    runtime: Any
    bvid: str
    transcript: dict[str, Any] | None
    video: dict[str, Any] | None
    transcript_hash: str
    existing_summary: dict[str, Any] | None
    merged_segments: list[dict[str, Any]]
    total_chars: int
    window_summaries: list[str]
    summary_text: str


def build_initial_summary_state(runtime: Any, bvid: str) -> SummaryState:
    return {
        "runtime": runtime,
        "bvid": bvid,
    }
