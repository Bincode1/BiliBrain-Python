from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from bilibrain.graphs.summary.nodes import (
    choose_summary_mode,
    generate_direct_summary,
    generate_window_summaries,
    load_summary_context,
    prepare_summary_segments,
    reduce_window_summaries,
    save_summary_result,
    should_return_cached_summary,
)
from bilibrain.graphs.summary.state import (
    SummaryContext,
    SummaryState,
    build_initial_summary_state,
)


@lru_cache(maxsize=1)
def get_summary_graph():
    builder = StateGraph(
        SummaryState,
        context_schema=SummaryContext,
    )
    builder.add_node("load_summary_context", load_summary_context)
    builder.add_node("prepare_summary_segments", prepare_summary_segments)
    builder.add_node("generate_direct_summary", generate_direct_summary)
    builder.add_node("generate_window_summaries", generate_window_summaries)
    builder.add_node("reduce_window_summaries", reduce_window_summaries)
    builder.add_node("save_summary_result", save_summary_result)

    builder.add_edge(START, "load_summary_context")
    builder.add_conditional_edges(
        "load_summary_context",
        should_return_cached_summary,
        {
            "no_transcript": END,
            "cached": END,
            "generate": "prepare_summary_segments",
        },
    )
    builder.add_conditional_edges(
        "prepare_summary_segments",
        choose_summary_mode,
        {
            "empty": END,
            "direct": "generate_direct_summary",
            "windowed": "generate_window_summaries",
        },
    )
    builder.add_edge("generate_direct_summary", "save_summary_result")
    builder.add_edge("generate_window_summaries", "reduce_window_summaries")
    builder.add_edge("reduce_window_summaries", "save_summary_result")
    builder.add_edge("save_summary_result", END)
    return builder.compile()


async def run_summary_graph(runtime, bvid: str) -> dict | None:
    graph = get_summary_graph()
    await graph.ainvoke(build_initial_summary_state(bvid), context={"runtime": runtime})
    return await runtime.db.get_video_summary(bvid)
