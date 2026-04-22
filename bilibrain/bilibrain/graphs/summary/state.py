from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from bilibrain.core.runtime import Runtime


class SummaryState(TypedDict, total=False):
    bvid: str
    transcript: dict[str, Any] | None
    video: dict[str, Any] | None
    transcript_hash: str
    existing_summary: dict[str, Any] | None
    merged_segments: list[dict[str, Any]]
    total_chars: int
    window_summaries: list[str]
    summary_text: str


class SummaryContext(TypedDict, total=False):
    runtime: Runtime


def build_initial_summary_state(bvid: str) -> SummaryState:
    return {
        "bvid": bvid,
    }
