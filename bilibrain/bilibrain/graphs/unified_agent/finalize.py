from __future__ import annotations

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime as GraphRuntime

from bilibrain.graphs.unified_agent.common import build_skills_state, emit_stream
from bilibrain.graphs.unified_agent.state import UnifiedAgentContext, UnifiedAgentState
from bilibrain.services.agent_common import summarize_tool_result_answer
from bilibrain.services.chat_storage import replace_chat_message
from bilibrain.services.chat_memory import refresh_context_stats_after_message
from bilibrain.services.citations import normalize_answer_citations
from bilibrain.services.task_execution import mark_task_failed, mark_task_rejected
from bilibrain.services import unified_agent as legacy_unified_agent


async def finalize_rejected(
    state: UnifiedAgentState,
    runtime: GraphRuntime[UnifiedAgentContext],
):
    context = runtime.context or {}
    app_runtime = context["runtime"]
    answer_text = str(state.get("answer_text") or "用户拒绝了当前操作。").strip()
    task_id = str(state.get("task_id") or "").strip() or None
    assistant_message_id = int(state.get("assistant_message_id") or 0) or None
    conversation_id = int(state["conversation_id"])
    tool_use_id = str(state.get("current_tool_use_id") or "").strip()

    assistant_message = (
        await replace_chat_message(
            app_runtime,
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            content=answer_text,
            task_id=task_id,
            message_kind="task_primary",
        )
        if assistant_message_id is not None
        else None
    )
    if assistant_message is not None:
        await refresh_context_stats_after_message(
            app_runtime,
            conversation_id=conversation_id,
            message=assistant_message,
        )
    if task_id:
        await mark_task_rejected(
            app_runtime,
            conversation_id=conversation_id,
            task_id=task_id,
            tool_use_id=tool_use_id,
            approval_id=None,
            decision={"type": "reject", "message": answer_text},
            failure_reason=answer_text,
        )
        emit_stream(
            "task_status",
            {
                "task_id": task_id,
                "assistant_message_id": assistant_message_id,
                "status": "failed",
                "phase": "rejected",
                "failure_reason": answer_text,
            },
        )
    return {"status": "completed", "answer_text": answer_text}


async def finalize_answer(
    state: UnifiedAgentState,
    runtime: GraphRuntime[UnifiedAgentContext],
):
    context = runtime.context or {}
    app_runtime = context["runtime"]
    conversation_id = int(state["conversation_id"])
    task_id = str(state.get("task_id") or "").strip() or None
    assistant_message_id = int(state.get("assistant_message_id") or 0) or None
    sources = list(state.get("collected_sources") or [])
    route_mode = str(state.get("route_mode") or ("kb_qa" if sources else "direct"))
    answer_text = str(state.get("answer_text") or "").strip() or "当前没有生成有效回答。"

    current_tool_result = str(state.get("current_tool_result") or "")
    last_tool_name = ""
    last_tool_args: dict[str, object] = {}
    messages = list(state.get("messages") or [])
    for item in reversed(messages):
        if isinstance(item, AIMessage):
            tool_calls = getattr(item, "tool_calls", None) or []
            if tool_calls:
                tc = tool_calls[-1]
                last_tool_name = str(tc.get("name") or "")
                last_tool_args = dict(tc.get("args") or {})
                break

    if last_tool_name in {"write_file", "append_file", "make_dir", "obsidian_write_note"} and current_tool_result:
        answer_text = normalize_answer_citations(
            summarize_tool_result_answer(
                last_tool_name,
                last_tool_args,
                current_tool_result,
                answer_text,
            )
        )
    post = await legacy_unified_agent._postprocess(
        app_runtime,
        answer_text=answer_text,
        sources=sources,
        conversation_id=conversation_id,
        task_id=task_id,
        route_mode=route_mode,
        placeholder_message_id=assistant_message_id,
    )
    emit_stream("answer_normalized", {"text": post["answer_text"]})
    emit_stream("context", await legacy_unified_agent.get_conversation_context_usage(app_runtime, conversation_id))
    if sources:
        emit_stream("sources", {"sources": sources})
    emit_stream("mode", {"mode": post["answer_mode"]})
    emit_stream("route", {"route_mode": route_mode})
    emit_stream("skills", build_skills_state(app_runtime, str(state.get("session_id") or "")))
    emit_stream(
        "task_status",
        {
            "task_id": task_id,
            "assistant_message_id": assistant_message_id,
            "status": "completed",
            "phase": "completed",
            "route_mode": route_mode,
            "answer_mode": post["answer_mode"],
        },
    )
    return {
        "status": "completed",
        "answer_text": post["answer_text"],
        "answer_mode": post["answer_mode"],
        "route_mode": route_mode,
    }


async def finalize_error(
    state: UnifiedAgentState,
    runtime: GraphRuntime[UnifiedAgentContext],
):
    context = runtime.context or {}
    app_runtime = context["runtime"]
    error_text = str(state.get("error") or "Unified agent 执行失败").strip()
    task_id = str(state.get("task_id") or "").strip() or None
    conversation_id = int(state["conversation_id"])
    assistant_message_id = int(state.get("assistant_message_id") or 0) or None
    if task_id:
        await mark_task_failed(
            app_runtime,
            conversation_id=conversation_id,
            task_id=task_id,
            failure_reason=error_text,
        )
        emit_stream(
            "task_status",
            {
                "task_id": task_id,
                "assistant_message_id": assistant_message_id,
                "status": "failed",
                "phase": "failed",
                "failure_reason": error_text,
            },
        )
    emit_stream("error", {"detail": error_text})
    return {"status": "failed", "error": error_text}
