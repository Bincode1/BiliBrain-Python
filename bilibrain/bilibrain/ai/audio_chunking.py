from __future__ import annotations

import re


SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")


def trim_repeated_prefix(previous_text: str, current_text: str, *, min_match_chars: int = 8) -> str:
    previous = str(previous_text or "").strip()
    current = str(current_text or "").strip()
    if not previous or not current:
        return current

    max_match = min(len(previous), len(current), 80)
    for size in range(max_match, min_match_chars - 1, -1):
        if previous[-size:] == current[:size]:
            return current[size:].lstrip(" ，,。！？!?；;：:")
    return current


def plan_silence_aligned_ranges(
    *,
    duration_seconds: float,
    silence_points: list[float],
    target_seconds: float,
    max_seconds: float,
) -> list[tuple[float, float]]:
    total_duration = max(float(duration_seconds), 0.0)
    if total_duration <= 0:
        return []

    safe_target = max(min(float(target_seconds), float(max_seconds)), 1.0)
    safe_max = max(float(max_seconds), safe_target)
    min_chunk = min(max(safe_target * 0.5, 20.0), safe_target)
    cut_points = sorted(
        {
            round(point, 3)
            for point in silence_points
            if min_chunk <= float(point) < total_duration
        }
    )

    ranges: list[tuple[float, float]] = []
    cursor = 0.0
    while cursor < total_duration:
        hard_end = min(cursor + safe_max, total_duration)
        if total_duration - cursor <= safe_max:
            end = total_duration
        else:
            preferred_end = min(cursor + safe_target, total_duration)
            candidates = [
                point
                for point in cut_points
                if cursor + min_chunk <= point <= hard_end
            ]
            if candidates:
                end = min(candidates, key=lambda point: (abs(point - preferred_end), point))
            else:
                end = hard_end

        if end <= cursor:
            end = min(cursor + safe_max, total_duration)
        ranges.append((round(cursor, 3), round(end, 3)))
        cursor = end

    return ranges
