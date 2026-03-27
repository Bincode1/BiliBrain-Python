from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict


class IngestionState(TypedDict, total=False):
    runtime: Any
    bvid: str
    current_step: str
    video: dict[str, Any] | None
    processing_settings: dict[str, int]
    max_video_minutes: int
    duration_seconds: int
    temp_audio_path: str
    transcript: dict[str, Any] | None
    merged_segments: list[dict[str, Any]]
    chunk_rows: list[dict[str, Any]]
    skip_summary: bool


def build_initial_state(
    runtime: Any,
    bvid: str,
    temp_audio_path: Path,
    *,
    skip_summary: bool = False,
) -> IngestionState:
    return {
        "runtime": runtime,
        "bvid": bvid,
        "current_step": "audio",
        "temp_audio_path": str(temp_audio_path),
        "skip_summary": bool(skip_summary),
    }
