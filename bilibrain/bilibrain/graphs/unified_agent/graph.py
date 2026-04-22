from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from bilibrain.graphs.unified_agent.nodes import (
    approval_gate,
    execute_tool,
    finalize_answer,
    finalize_error,
    finalize_rejected,
    load_context,
    model_step,
    select_next_tool_call,
)
from bilibrain.graphs.unified_agent.state import UnifiedAgentContext, UnifiedAgentState


def build_unified_agent_graph(*, checkpointer=None):
    builder = StateGraph(
        UnifiedAgentState,
        context_schema=UnifiedAgentContext,
    )
    builder.add_node("load_context", load_context)
    builder.add_node("model_step", model_step)
    builder.add_node("select_next_tool_call", select_next_tool_call)
    builder.add_node("approval_gate", approval_gate)
    builder.add_node("execute_tool", execute_tool)
    builder.add_node("finalize_rejected", finalize_rejected)
    builder.add_node("finalize_answer", finalize_answer)
    builder.add_node("finalize_error", finalize_error)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "model_step")
    builder.add_edge("select_next_tool_call", "approval_gate")
    builder.add_edge("finalize_rejected", END)
    builder.add_edge("finalize_answer", END)
    builder.add_edge("finalize_error", END)

    return builder.compile(checkpointer=checkpointer, name="unified_agent")


@lru_cache(maxsize=1)
def get_unified_agent_graph():
    return build_unified_agent_graph()
