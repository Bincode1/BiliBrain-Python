from __future__ import annotations

from langgraph.runtime import Runtime as GraphRuntime

from bilibrain.chat.assembler import assemble_unified_agent_context
from bilibrain.services.retrieval_support import describe_query_scope
from bilibrain.graphs.unified_agent.common import (
    build_event_callback,
    build_skills_state,
    emit_stream,
    tool_name,
)
from bilibrain.graphs.unified_agent.state import UnifiedAgentContext, UnifiedAgentState
from bilibrain.services.summary import resolve_query_scope
from bilibrain.tools.qa_tools import build_qa_retrieval_tools
from bilibrain.services import unified_agent as legacy_unified_agent


async def load_context(
    state: UnifiedAgentState,
    runtime: GraphRuntime[UnifiedAgentContext],
):
    context = runtime.context or {}
    app_runtime = context["runtime"]
    actor = str(context.get("actor") or "agent")
    query = str(state.get("query") or "").strip()
    folder_id = state.get("folder_id")
    bvid = state.get("bvid")
    scope_mode = state.get("scope_mode")
    conversation_id = int(state["conversation_id"])
    session_id = state.get("session_id") or legacy_unified_agent.build_unified_session_id(
        conversation_id=conversation_id,
    )

    workspace_id = str(state.get("workspace_id") or "").strip()
    if not workspace_id:
        workspace = await legacy_unified_agent.get_default_workspace(app_runtime, actor=actor)
        workspace_id = str(workspace.get("workspace_id") or "default").strip() or "default"

    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    scope_description = await describe_query_scope(
        app_runtime,
        folder_id=scope["folder_id"] if scope["scope"] == "folder" else folder_id,
        bvid=scope["bvid"] if scope["scope"] == "video" else bvid,
        scope_mode=scope_mode,
    )

    emit_stream("status", {"delta": "正在准备会话上下文..."})
    assembled = await assemble_unified_agent_context(
        app_runtime,
        conversation_id=conversation_id,
        query=query,
        system_prompt_builder=lambda memory_text: legacy_unified_agent.build_unified_agent_prompt(
            app_runtime,
            session_id=session_id,
            workspace_id=workspace_id,
            scope_description=scope_description,
            memory_text=memory_text,
            actor=actor,
        ),
        system_context_builder=lambda memory_text: legacy_unified_agent.build_unified_agent_context_prompt(
            app_runtime,
            session_id=session_id,
            workspace_id=workspace_id,
            scope_description=scope_description,
            memory_text=memory_text,
            actor=actor,
        ),
    )
    emit_stream("skills", build_skills_state(app_runtime, session_id))
    return {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "scope": scope,
        "scope_description": scope_description,
        "messages": list(assembled.messages),
        "context_snapshot": {
            "selected_live_prefix_message_ids": assembled.selected_live_prefix_message_ids,
            "selected_recent_message_ids": assembled.selected_recent_message_ids,
            "selected_workspace_state_keys": assembled.selected_workspace_state_keys,
            "token_estimates": assembled.token_estimates,
            "final_message_count": assembled.final_message_count,
        },
        "collected_sources": [],
        "pending_tool_calls": [],
        "current_tool_call": None,
        "current_tool_use_id": None,
        "current_tool_approval_mode": None,
        "current_tool_result": None,
        "pending_answer_text": "",
        "answer_text": "",
        "status": "running",
        "route_mode": None,
        "answer_mode": None,
        "error": None,
    }


def build_tools(
    state: UnifiedAgentState,
    runtime: GraphRuntime[UnifiedAgentContext],
):
    context = runtime.context or {}
    app_runtime = context["runtime"]
    actor = str(context.get("actor") or "agent")
    approval_mode = state.get("current_tool_approval_mode")
    if approval_mode is None:
        approval_mode = context.get("approval_mode")
    event_callback = build_event_callback(state, runtime)
    new_sources: list[dict[str, str]] = []

    def qa_event_callback(event_type: str, data: dict) -> None:
        if event_type == "sources" and data.get("sources"):
            new_sources.extend(data["sources"])
        event_callback(event_type, data)

    qa_tools = build_qa_retrieval_tools(
        app_runtime,
        folder_id=state.get("folder_id"),
        bvid=state.get("bvid"),
        event_callback=qa_event_callback,
    )
    skill_tools = legacy_unified_agent.build_skill_langchain_tools(
        app_runtime.skill_service,
        session_id=str(state.get("session_id") or ""),
        actor=actor,
        event_callback=event_callback,
    )
    workspace_tool_kwargs = {
        "workspace_id": str(state.get("workspace_id") or "default"),
        "actor": actor,
        "event_callback": event_callback,
    }
    if approval_mode is not None:
        workspace_tool_kwargs["approval_mode"] = approval_mode
    workspace_tools = legacy_unified_agent.build_langchain_tools(
        app_runtime.tool_service,
        **workspace_tool_kwargs,
    )
    tools = [*qa_tools, *skill_tools, *workspace_tools]
    tool_map = {tool_name(tool): tool for tool in tools}
    return tools, tool_map, new_sources
