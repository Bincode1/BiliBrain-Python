from __future__ import annotations

from bilibrain.eval_adapter.contracts import EvalRequest, EvalResult
from bilibrain.eval_adapter.policy import build_eval_execution_policy
from bilibrain.eval_adapter.trace import build_eval_trace
from bilibrain.graphs.qa import run_qa_graph_capture


async def run_eval_case(runtime, request: EvalRequest) -> EvalResult:
    final_state = await run_qa_graph_capture(
        runtime=runtime,
        query=request.query,
        folder_id=request.folder_id,
        bvid=request.bvid,
        scope_mode=request.scope_mode,
        execution_policy=build_eval_execution_policy(request),
    )
    trace = build_eval_trace(final_state)
    return EvalResult(
        query=request.query,
        response=str(final_state.get("answer_text") or "").strip(),
        route_mode=trace.route_mode,
        retrieval_mode=trace.retrieval_mode,
        strategy_name=request.strategy_name,
        conversation_id=final_state.get("conversation_id"),
        retrieved_contexts=trace.retrieved_contexts,
        retrieved_items=trace.retrieved_items,
        sources=trace.sources,
        timings=trace.timings,
    )
