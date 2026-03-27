from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, AsyncIterator

from langgraph.graph import END, START, StateGraph

from bilibrain.graphs.research.events import make_sse_event
from bilibrain.graphs.research.nodes import (
    analyze_retrievals,
    append_assistant_message,
    append_user_message,
    load_kb_snapshot,
    orchestrate_subtasks,
    prepare_research_workspace,
    resolve_scope_and_conversation,
    run_retrieval,
    write_report,
)
from bilibrain.graphs.research.state import ResearchState, build_initial_research_state


@lru_cache(maxsize=1)
def get_research_graph():
    builder = StateGraph(ResearchState)

    builder.add_node("resolve_scope", resolve_scope_and_conversation)
    builder.add_node("append_user", append_user_message)
    builder.add_node("prepare_workspace", prepare_research_workspace)
    builder.add_node("load_kb_snapshot", load_kb_snapshot)
    builder.add_node("orchestrate_subtasks", orchestrate_subtasks)
    builder.add_node("run_retrieval", run_retrieval)
    builder.add_node("analyze_retrievals", analyze_retrievals)
    builder.add_node("write_report", write_report)
    builder.add_node("append_assistant", append_assistant_message)

    builder.add_edge(START, "resolve_scope")
    builder.add_edge("resolve_scope", "append_user")
    builder.add_edge("append_user", "prepare_workspace")
    builder.add_edge("prepare_workspace", "load_kb_snapshot")
    builder.add_edge("load_kb_snapshot", "orchestrate_subtasks")
    builder.add_edge("orchestrate_subtasks", "run_retrieval")
    builder.add_edge("run_retrieval", "analyze_retrievals")
    builder.add_edge("analyze_retrievals", "write_report")
    builder.add_edge("write_report", "append_assistant")
    builder.add_edge("append_assistant", END)

    return builder.compile()


async def run_research_graph(
    runtime: Any,
    query: str,
    folder_id: int | None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
    *,
    streaming: bool = False,
) -> dict[str, Any]:
    graph = get_research_graph()
    final_state = await graph.ainvoke(
        build_initial_research_state(
            runtime=runtime,
            query=query,
            folder_id=folder_id,
            bvid=bvid,
            scope_mode=scope_mode,
            conversation_id=conversation_id,
            streaming=streaming,
        )
    )
    return {
        "conversation_id": final_state.get("conversation_id"),
        "answer": final_state.get("answer_text") or "",
        "sources": final_state.get("sources") or [],
        "answer_mode": "research",
        "route_mode": "research",
    }


async def run_research_graph_stream(
    runtime: Any,
    query: str,
    folder_id: int | None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
) -> AsyncIterator[str]:
    graph = get_research_graph()
    initial_state = build_initial_research_state(
        runtime=runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        conversation_id=conversation_id,
        streaming=True,
    )

    conversation_id_sent = False
    mode_sent = False

    try:
        async for chunk in graph.astream(initial_state, stream_mode=["custom", "updates"], version="v2"):
            chunk_type = chunk.get("type")
            if chunk_type == "custom":
                custom_data = chunk.get("data") or {}
                if custom_data.get("_status"):
                    yield make_sse_event("status", {"delta": custom_data["_status"]})
                if custom_data.get("_mode") and not mode_sent:
                    yield make_sse_event("mode", {"mode": custom_data["_mode"]})
                    mode_sent = True
                if custom_data.get("_research_plan"):
                    yield make_sse_event("research_plan", custom_data["_research_plan"])
                if custom_data.get("_agent"):
                    yield make_sse_event("agent", custom_data["_agent"])
                if custom_data.get("_answer_token"):
                    yield f"event: answer\ndata: {json.dumps({'delta': custom_data['_answer_token']}, ensure_ascii=False)}\n\n"

            elif chunk_type == "updates":
                updates = chunk.get("data") or {}
                for node_name, node_data in updates.items():
                    if not isinstance(node_data, dict):
                        continue
                    if node_name == "resolve_scope" and not conversation_id_sent:
                        conv_id = node_data.get("conversation_id")
                        if conv_id:
                            yield make_sse_event("conversation", {"conversation_id": conv_id})
                            conversation_id_sent = True
                    if node_data.get("sources"):
                        yield make_sse_event("sources", {"sources": node_data["sources"]})

    except Exception as exc:
        yield make_sse_event("error", {"detail": str(exc)})

    yield make_sse_event("done")
