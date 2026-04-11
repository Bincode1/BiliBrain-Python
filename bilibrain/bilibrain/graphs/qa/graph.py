from __future__ import annotations

import json
from functools import lru_cache
from time import perf_counter
from typing import Any, AsyncIterator

from langgraph.graph import END, START, StateGraph

from bilibrain.graphs.qa.events import make_sse_event
from bilibrain.graphs.qa.nodes import (
    append_assistant_message,
    append_user_message,
    compact_memory_if_needed,
    final_answer,
    load_conversation_context,
    plan_query_route,
    prepare_data_for_answer,
    resolve_effective_context,
    resolve_scope_and_conversation,
)
from bilibrain.graphs.qa.state import QAState, build_initial_qa_state


@lru_cache(maxsize=1)
def get_qa_graph():
    builder = StateGraph(QAState)

    builder.add_node("resolve_scope", resolve_scope_and_conversation)
    builder.add_node("load_context", load_conversation_context)
    builder.add_node("compact_memory", compact_memory_if_needed)
    builder.add_node("append_user", append_user_message)
    builder.add_node("plan_route", plan_query_route)
    builder.add_node("resolve_effective_context", resolve_effective_context)
    builder.add_node("prepare_data", prepare_data_for_answer)
    builder.add_node("final_answer", final_answer)
    builder.add_node("append_assistant", append_assistant_message)

    builder.add_edge(START, "resolve_scope")
    builder.add_edge("resolve_scope", "load_context")
    builder.add_edge("load_context", "compact_memory")
    builder.add_edge("compact_memory", "append_user")
    builder.add_edge("append_user", "plan_route")
    builder.add_edge("plan_route", "resolve_effective_context")
    builder.add_edge("resolve_effective_context", "prepare_data")
    builder.add_edge("prepare_data", "final_answer")
    builder.add_edge("final_answer", "append_assistant")
    builder.add_edge("append_assistant", END)

    return builder.compile()


async def run_qa_graph(
    runtime: Any,
    query: str,
    folder_id: int | None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
    *,
    execution_policy: dict[str, Any] | None = None,
    streaming: bool = False,
) -> dict[str, Any]:
    graph = get_qa_graph()

    initial_state = build_initial_qa_state(
        runtime=runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        conversation_id=conversation_id,
        execution_policy=execution_policy,
        streaming=streaming,
    )

    final_state = await graph.ainvoke(initial_state)

    return {
        "conversation_id": final_state.get("conversation_id"),
        "answer": final_state.get("answer_text") or "",
        "sources": final_state.get("sources") or [],
        "answer_mode": _determine_answer_mode(final_state),
        "route_mode": final_state.get("route_mode"),
    }


async def run_qa_graph_capture(
    runtime: Any,
    query: str,
    folder_id: int | None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
    *,
    execution_policy: dict[str, Any] | None = None,
) -> QAState:
    graph = get_qa_graph()
    started = perf_counter()

    initial_state = build_initial_qa_state(
        runtime=runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        conversation_id=conversation_id,
        execution_policy=execution_policy,
        streaming=False,
    )

    final_state = await graph.ainvoke(initial_state)
    timings = dict(final_state.get("timings") or {})
    timings["total_ms"] = round((perf_counter() - started) * 1000, 3)
    final_state["timings"] = timings
    return final_state


async def run_qa_graph_stream(
    runtime: Any,
    query: str,
    folder_id: int | None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
) -> AsyncIterator[str]:
    graph = get_qa_graph()

    initial_state = build_initial_qa_state(
        runtime=runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        conversation_id=conversation_id,
        streaming=True,
    )

    conversation_id_sent = False

    try:
        async for chunk in graph.astream(
            initial_state,
            stream_mode=["custom", "updates"],
            version="v2",
        ):
            chunk_type = chunk.get("type")

            if chunk_type == "custom":
                custom_data = chunk.get("data")
                if custom_data and isinstance(custom_data, dict):
                    if custom_data.get("_status"):
                        yield make_sse_event("status", {"delta": custom_data["_status"]})
                    if custom_data.get("_route_mode"):
                        yield make_sse_event("route", {"route_mode": custom_data["_route_mode"]})
                    if custom_data.get("_mode"):
                        yield make_sse_event("mode", {"mode": custom_data["_mode"]})
                    if custom_data.get("_answer_token"):
                        delta = custom_data["_answer_token"]
                        yield f"event: answer\ndata: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
                    if custom_data.get("_answer_normalized"):
                        yield make_sse_event("answer_normalized", {"text": custom_data["_answer_normalized"]})

            elif chunk_type == "updates":
                raw_data = chunk.get("data") or {}
                node_name = next(iter(raw_data), None)
                node_data = raw_data[node_name] if node_name else {}

                if node_name == "resolve_scope" and not conversation_id_sent:
                    conv_id = node_data.get("conversation_id")
                    if conv_id:
                        yield make_sse_event("conversation", {"conversation_id": conv_id})
                        conversation_id_sent = True

                if node_data.get("_status"):
                    yield make_sse_event("status", {"delta": node_data["_status"]})
                if node_data.get("_route_mode"):
                    yield make_sse_event("route", {"route_mode": node_data["_route_mode"]})
                if node_data.get("_mode"):
                    yield make_sse_event("mode", {"mode": node_data["_mode"]})
                if node_data.get("sources"):
                    yield make_sse_event("sources", {"sources": node_data["sources"]})

    except Exception as exc:
        yield make_sse_event("error", {"detail": str(exc)})

    yield make_sse_event("done")


def _determine_answer_mode(state: QAState) -> str | None:
    route_mode = state.get("route_mode")
    sources = state.get("sources") or []

    if route_mode == "direct":
        return None

    if sources:
        first_source = sources[0]
        return "summary" if first_source.get("source_kind") == "summary" else "chunk"

    return "chunk"
