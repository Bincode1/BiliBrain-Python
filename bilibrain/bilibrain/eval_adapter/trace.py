from __future__ import annotations

from typing import Any

from bilibrain.eval_adapter.contracts import EvalTrace


def build_eval_trace(final_state: dict[str, Any]) -> EvalTrace:
    matches = list(final_state.get("matches") or [])
    documents = list(final_state.get("documents") or [])
    route_mode = final_state.get("route_mode")
    retrieval_mode = final_state.get("retrieval_mode")

    if documents:
        retrieved_contexts = [str(item.get("summary_text") or "").strip() for item in documents if str(item.get("summary_text") or "").strip()]
        retrieved_items = documents
    else:
        retrieved_contexts = [str(item.get("content") or "").strip() for item in matches if str(item.get("content") or "").strip()]
        retrieved_items = matches

    timings = {
        key: round(float(value), 3)
        for key, value in dict(final_state.get("timings") or {}).items()
        if value is not None
    }

    return EvalTrace(
        route_mode=(str(route_mode).strip() or None) if route_mode is not None else None,
        retrieval_mode=(str(retrieval_mode).strip() or None) if retrieval_mode is not None else None,
        retrieved_contexts=retrieved_contexts,
        retrieved_items=retrieved_items,
        sources=list(final_state.get("sources") or []),
        timings=timings,
    )
