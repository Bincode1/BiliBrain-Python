from __future__ import annotations

import json
from typing import Any


def make_sse_event(event_type: str, data: dict[str, Any] | None = None) -> str:
    payload = json.dumps(data or {}, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"
