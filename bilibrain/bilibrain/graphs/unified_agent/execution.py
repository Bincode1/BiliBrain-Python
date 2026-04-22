from __future__ import annotations

import json

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime as GraphRuntime
from langgraph.types import Command, interrupt

from bilibrain.graphs.unified_agent.approvals import (
    build_approval_request,
    build_skill_approval_request,
)
from bilibrain.graphs.unified_agent.common import (
    emit_stream,
    merge_collected_sources,
    merge_decision_args,
    normalize_tool_result,
    now_text,
)
from bilibrain.graphs.unified_agent.context import build_tools
from bilibrain.graphs.unified_agent.state import UnifiedAgentContext, UnifiedAgentState
from bilibrain.services.chat_storage import (
    append_chat_tool_use,
    get_chat_session_task,
    get_chat_session_tool_use,
    replace_chat_tool_use,
)
from bilibrain.services.task_execution import mark_task_running_after_approval
from bilibrain.services import unified_agent as legacy_unified_agent

_HITL_TOOLS = {"run_command", "write_file", "append_file", "make_dir", "obsidian_write_note"}


def _tool_use_event_payload(tool_use: dict[str, object] | None) -> dict[str, object]:
    payload = dict(tool_use or {})
    return {
        "tool_use_id": payload.get("tool_use_id"),
        "task_id": payload.get("task_id"),
        "tool_name": payload.get("tool_name"),
        "status": payload.get("status"),
        "input_summary": payload.get("input_summary") or {},
        "raw_input": payload.get("raw_input") or {},
        "raw_output": payload.get("raw_output"),
        "error": payload.get("error"),
        "request_id": payload.get("request_id"),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "updated_at": payload.get("updated_at"),
    }


async def model_step(
    state: UnifiedAgentState,
    runtime: GraphRuntime[UnifiedAgentContext],
):
    context = runtime.context or {}
    app_runtime = context["runtime"]
    stream = bool(context.get("stream"))
    messages = list(state.get("messages") or [])
    if not messages:
        return Command(update={"error": "Unified agent graph 缺少消息上下文。"}, goto="finalize_error")

    emit_stream("status", {"delta": "正在思考并决定下一步..."})
    tools, _, _ = build_tools(state, runtime)
    llm = app_runtime.qwen.model.bind_tools(tools)

    full_text = ""
    tool_call_chunks_acc: list[dict[str, str | int]] = []

    async for chunk in llm.astream(messages):
        tc_chunks = getattr(chunk, "tool_call_chunks", None) or []
        for tcc in tc_chunks:
            if isinstance(tcc, dict):
                name = tcc.get("name")
                args_str = tcc.get("args", "")
                tc_id = tcc.get("id")
                idx = tcc.get("index", 0)
            else:
                name = getattr(tcc, "name", None)
                args_str = getattr(tcc, "args", "")
                tc_id = getattr(tcc, "id", None)
                idx = getattr(tcc, "index", 0)
            while len(tool_call_chunks_acc) <= idx:
                tool_call_chunks_acc.append({"name": "", "args": "", "id": ""})
            entry = tool_call_chunks_acc[idx]
            if name:
                entry["name"] = name
            if args_str:
                entry["args"] += args_str
            if tc_id:
                entry["id"] = tc_id

        msg = getattr(chunk, "message", chunk)
        reasoning = (
            getattr(msg, "additional_kwargs", {}).get("reasoning_content")
            if hasattr(msg, "additional_kwargs")
            else None
        )
        if isinstance(reasoning, str) and reasoning:
            emit_stream("reasoning", {"delta": reasoning})

        content = getattr(chunk, "content", None)
        if isinstance(content, str) and content and not tc_chunks:
            full_text += content
            if stream:
                emit_stream("answer_token", {"delta": content})

    has_tool_calls = bool(tool_call_chunks_acc) and any(
        entry.get("name") for entry in tool_call_chunks_acc
    )
    if not has_tool_calls:
        answer_text = full_text.strip()
        return Command(
            update={
                "answer_text": answer_text,
                "route_mode": "kb_qa" if state.get("collected_sources") else "direct",
                "answer_mode": None,
                "pending_answer_text": "",
            },
            goto="finalize_answer",
        )

    tool_calls: list[dict] = []
    for entry in tool_call_chunks_acc:
        if not entry.get("name"):
            continue
        args_raw = str(entry.get("args") or "")
        try:
            args = json.loads(args_raw) if args_raw else {}
        except json.JSONDecodeError:
            args = {}
        tool_calls.append(
            {
                "name": entry["name"],
                "args": args,
                "id": entry.get("id", ""),
            }
        )

    messages.append(AIMessage(content=full_text, tool_calls=tool_calls))
    return Command(
        update={
            "messages": messages,
            "pending_tool_calls": tool_calls,
            "pending_answer_text": full_text.strip(),
        },
        goto="select_next_tool_call",
    )


async def select_next_tool_call(
    state: UnifiedAgentState,
    runtime: GraphRuntime[UnifiedAgentContext],
):
    _ = runtime
    queue = list(state.get("pending_tool_calls") or [])
    if not queue:
        return Command(goto="model_step")
    current = dict(queue[0] or {})
    remaining = queue[1:]
    tool_use_id = str(current.get("id") or "").strip() or f"tool-{len(remaining)}"
    return {
        "current_tool_call": current,
        "current_tool_use_id": tool_use_id,
        "pending_tool_calls": remaining,
    }


async def approval_gate(
    state: UnifiedAgentState,
    runtime: GraphRuntime[UnifiedAgentContext],
):
    context = runtime.context or {}
    app_runtime = context["runtime"]
    actor = str(context.get("actor") or "agent")
    current = dict(state.get("current_tool_call") or {})
    tool_name = str(current.get("name") or "").strip()
    tool_args = dict(current.get("args") or {})
    tool_call_id = str(current.get("id") or state.get("current_tool_use_id") or "").strip()
    conversation_id = int(state["conversation_id"])
    task_id = str(state.get("task_id") or "").strip()
    tool_use_id = str(state.get("current_tool_use_id") or tool_call_id).strip()

    if tool_name not in _HITL_TOOLS and tool_name != "skill":
        return Command(goto="execute_tool")

    if tool_name == "skill":
        skill_name = str(tool_args.get("name") or "").strip()
        decision = app_runtime.skill_service.evaluate_skill_access(
            name=skill_name,
            session_id=str(state.get("session_id") or ""),
            actor=actor,
        ) if app_runtime.skill_service is not None else None
        if decision is None or not decision.requires_approval:
            return Command(goto="execute_tool")
        approval_request = build_skill_approval_request(
            app_runtime,
            skill_name=skill_name,
            tool_call_id=tool_call_id,
            session_id=str(state.get("session_id") or ""),
            actor=actor,
        )
    else:
        approval_request = build_approval_request(
            app_runtime,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
        )
        cached = await get_chat_session_tool_use(app_runtime, conversation_id, tool_use_id)
        pending_tool_use = cached
        if pending_tool_use is None:
            pending_tool_use = await append_chat_tool_use(
                app_runtime,
                conversation_id,
                tool_use_id=tool_use_id,
                task_id=task_id,
                tool_name=tool_name,
                status="pending",
                input_summary=legacy_unified_agent._summarize_tool_args(tool_name, tool_args),
                raw_input=tool_args,
                request_id=tool_use_id,
            )
        emit_stream("tool_use", _tool_use_event_payload(pending_tool_use))

    decision = interrupt(approval_request)
    decision_type = str((decision or {}).get("type") or "").strip().lower() or "approve"
    if decision_type == "reject":
        return Command(
            update={
                "answer_text": str((decision or {}).get("message") or "用户拒绝了当前操作。").strip(),
                "status": "rejected",
                "approval_request": approval_request,
            },
            goto="finalize_rejected",
        )

    effective_args = merge_decision_args(
        {"args": tool_args},
        decision if isinstance(decision, dict) else {},
    )
    if tool_name == "skill" and app_runtime.skill_service is not None:
        app_runtime.skill_service.approve_skill(
            name=str(effective_args.get("name") or ""),
            session_id=str(state.get("session_id") or ""),
        )
    if state.get("task_id"):
        await mark_task_running_after_approval(
            app_runtime,
            conversation_id=int(state["conversation_id"]),
            task_id=str(state["task_id"]),
            tool_use_id=str(state.get("current_tool_use_id") or tool_call_id),
            decision=dict(decision or {}),
        )
        emit_stream(
            "task_status",
            {
                "task_id": state.get("task_id"),
                "assistant_message_id": state.get("assistant_message_id"),
                "status": "running",
                "phase": "running",
            },
        )
    return Command(
        update={"current_tool_call": {**current, "args": effective_args}},
        goto="execute_tool",
    )


async def execute_tool(
    state: UnifiedAgentState,
    runtime: GraphRuntime[UnifiedAgentContext],
):
    context = runtime.context or {}
    app_runtime = context["runtime"]
    conversation_id = int(state["conversation_id"])
    task_id = str(state.get("task_id") or "").strip()
    current = dict(state.get("current_tool_call") or {})
    tool_name = str(current.get("name") or "").strip()
    tool_args = dict(current.get("args") or {})
    tool_use_id = str(state.get("current_tool_use_id") or current.get("id") or "").strip()

    cached = await get_chat_session_tool_use(app_runtime, conversation_id, tool_use_id)
    result_str = ""
    new_sources: list[dict[str, str]] = []

    if cached and (cached.get("raw_output") is not None or cached.get("error") is not None):
        if cached.get("raw_output") is not None:
            result_str = json.dumps(cached["raw_output"], ensure_ascii=False)
        elif cached.get("error") is not None:
            result_str = json.dumps({"error": cached["error"]}, ensure_ascii=False)
        emit_stream("tool_use", _tool_use_event_payload(cached))
    else:
        tools, tool_map, new_sources = build_tools(state, runtime)
        tool = tool_map.get(tool_name)
        if tool is None:
            result_str = json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)
        else:
            if not cached:
                created_tool_use = await append_chat_tool_use(
                    app_runtime,
                    conversation_id,
                    tool_use_id=tool_use_id,
                    task_id=task_id,
                    tool_name=tool_name,
                    status="pending",
                    input_summary=legacy_unified_agent._summarize_tool_args(tool_name, tool_args),
                    raw_input=tool_args,
                    request_id=tool_use_id,
                )
                emit_stream("tool_use", _tool_use_event_payload(created_tool_use))
            try:
                raw_result = await tool.ainvoke(tool_args)
            except Exception as exc:
                raw_result = {"error": str(exc)}
            result_str, parsed = normalize_tool_result(raw_result)
            final_tool_use = await replace_chat_tool_use(
                app_runtime,
                conversation_id,
                tool_use_id=tool_use_id,
                status="completed" if not (parsed or {}).get("error") else "failed",
                raw_input=tool_args,
                raw_output=parsed if parsed is not None else {"text": result_str},
                error=(parsed or {}).get("error") if isinstance((parsed or {}).get("error"), dict) else (
                    {"message": str((parsed or {}).get("error") or "")} if (parsed or {}).get("error") else None
                ),
                request_id=tool_use_id,
                finished_at=now_text(),
            )
            emit_stream("tool_use", _tool_use_event_payload(final_tool_use))

    messages = list(state.get("messages") or [])
    tool_call_id = str(current.get("id") or tool_use_id)
    messages.append(ToolMessage(content=result_str, tool_call_id=tool_call_id))

    if tool_name == "run_command" and task_id:
        try:
            payload = json.loads(result_str)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and (payload.get("error") or payload.get("ok") is False):
            await legacy_unified_agent.mark_command_failed(
                app_runtime,
                conversation_id=conversation_id,
                task_id=task_id,
                command=str(tool_args.get("command") or ""),
                exit_code=int(((payload.get("payload") or {}) or {}).get("exit_code") or -1),
                stderr=str(((payload.get("payload") or {}) or {}).get("stderr") or ""),
                retry_count=int((await get_chat_session_task(app_runtime, conversation_id, task_id) or {}).get("retry_count") or 0) + 1,
            )

    next_goto = "select_next_tool_call" if state.get("pending_tool_calls") else "model_step"
    return Command(
        update={
            "messages": messages,
            "current_tool_result": result_str,
            "current_tool_call": None,
            "current_tool_use_id": None,
            "collected_sources": merge_collected_sources(
                list(state.get("collected_sources") or []),
                new_sources,
            ),
        },
        goto=next_goto,
    )
