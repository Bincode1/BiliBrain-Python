from __future__ import annotations

from dataclasses import asdict
from typing import Any

from bilibrain.eval_adapter.contracts import EvalExecutionPolicy, EvalRequest


def build_eval_execution_policy(
    request: EvalRequest | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    payload = asdict(EvalExecutionPolicy())
    if request is not None:
        payload.update(
            {
                "persist_messages": bool(request.persist_messages),
                "load_history": bool(request.load_history),
                "planner_enabled": bool(request.planner_enabled),
                "retrieval_top_k": max(int(request.retrieval_top_k), 1),
                "rerank_top_k": max(int(request.rerank_top_k), 1),
            }
        )
    payload.update({key: value for key, value in overrides.items() if value is not None})
    payload["retrieval_top_k"] = max(int(payload.get("retrieval_top_k") or 40), 1)
    payload["rerank_top_k"] = max(int(payload.get("rerank_top_k") or 10), 1)
    payload["persist_messages"] = bool(payload.get("persist_messages"))
    payload["load_history"] = bool(payload.get("load_history"))
    payload["planner_enabled"] = bool(payload.get("planner_enabled", True))
    return payload
