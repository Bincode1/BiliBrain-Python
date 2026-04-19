from __future__ import annotations

from typing import Any


def build_index_payload(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        sessions,
        key=lambda item: (
            str(item.get("updated_at") or ""),
            int(item.get("conversation_id") or 0),
        ),
        reverse=True,
    )
    return {"sessions": ordered}
