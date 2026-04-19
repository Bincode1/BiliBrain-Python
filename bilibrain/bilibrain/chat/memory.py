from __future__ import annotations


def normalize_memory_text(value: str | None) -> str:
    return str(value or "").strip()
