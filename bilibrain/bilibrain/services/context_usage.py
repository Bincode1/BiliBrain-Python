from __future__ import annotations

import json
from typing import Any

from bilibrain.chat.paths import get_context_layers_path
from bilibrain.services.chat_storage import read_chat_session_context_stats


def _read_context_layer_total_tokens(runtime, conversation_id: int) -> int:
    path = get_context_layers_path(runtime.settings, int(conversation_id))
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    token_estimates = payload.get("token_estimates") if isinstance(payload, dict) else None
    if not isinstance(token_estimates, dict):
        return 0
    return int(token_estimates.get("total") or 0)


async def get_conversation_context_usage(
    runtime,
    conversation_id: int,
) -> dict[str, Any]:
    resolved_id = int(conversation_id)
    stats = await read_chat_session_context_stats(runtime, resolved_id)
    if stats:
        current_tokens = (
            int(stats.get("memory_token_estimate") or 0)
            + int(stats.get("uncompacted_token_estimate") or 0)
            + int(stats.get("recent_token_estimate") or 0)
        )
    else:
        current_tokens = _read_context_layer_total_tokens(runtime, resolved_id)

    return {
        "conversation_id": resolved_id,
        "current_tokens": max(int(current_tokens), 0),
        "limit_tokens": int(runtime.settings.chat_compaction_trigger_tokens or 0),
    }
