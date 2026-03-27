from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Callable

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.types import Command, GraphOutput, Interrupt

from bilibrain.core.runtime import Runtime
from bilibrain.graphs.qa.events import make_sse_event
from bilibrain.skills import build_skill_langchain_tools
from bilibrain.tools import build_langchain_tools
from bilibrain.tools.policy import evaluate_command_request


def build_skill_agent_session_id(*, conversation_id: int | None = None, explicit_session_id: str | None = None) -> str:
    explicit = str(explicit_session_id or "").strip()
    if explicit:
        return explicit
    if conversation_id:
        return f"conversation-{int(conversation_id)}"
    raise RuntimeError("Skill agent session_id is required when conversation_id is not provided.")


def build_skill_agent_prompt(
    runtime: Runtime,
    *,
    session_id: str,
    workspace_id: str,
) -> str:
    available_skills = runtime.skill_service.build_available_skills_prompt(session_id=session_id) if runtime.skill_service else "<available_skills />"
    active_skills = runtime.skill_service.build_active_skills_prompt(session_id=session_id) if runtime.skill_service else "<active_skills />"
    tools = runtime.tool_service.list_tools() if runtime.tool_service else []
    tool_lines = []
    for item in tools:
        if not item.get("enabled", True):
            continue
        tool_lines.append(f"- {item['name']}: {item['description']}")
    tool_block = "\n".join(tool_lines) if tool_lines else "- 当前没有可用工具"

    return "\n".join(
        [
            "你是 BiliBrain 的 Skill Agent。",
            "你的职责是结合会话上下文、可用 skills 和 workspace tools 来完成任务。",
            "原则：",
            "1. 如果任务明显属于某个技能场景，先调用 activate_skill，再依据技能说明做事。",
            "2. 不要假装某个 skill 已激活；如果要使用技能方法论，必须先显式 activate_skill。",
            "3. 能用已有 active skills 解决时，不要重复激活相同 skill。",
            "4. 对文件和命令操作保持克制，只在当前 workspace 内工作。",
            "5. 如果工具由于审批策略失败，要明确告诉用户需要预批准，而不是伪造执行结果。",
            "",
            f"当前 workspace_id: {workspace_id}",
            "",
            "当前可用工具：",
            tool_block,
            "",
            "当前可用 skills：",
            available_skills,
            "",
            "当前已激活 skills：",
            active_skills,
        ]
    )


def ensure_skill_agent_conversation(runtime: Runtime, conversation_id: int | None) -> dict[str, Any]:
    if conversation_id:
        conversation = runtime.db.get_chat_conversation(int(conversation_id))
        if not conversation:
            raise RuntimeError("对话会话不存在，请刷新页面后重试。")
        return conversation
    return runtime.db.create_chat_conversation(None, title="")


def ensure_skill_agent_workspace(runtime: Runtime, *, conversation_id: int, actor: str) -> dict[str, Any]:
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")
    return runtime.tool_service.create_workspace(
        feature_name="skill-agent",
        conversation_id=conversation_id,
        title=f"Skill Agent {conversation_id}",
        actor=actor,
    )


def build_skill_agent_history(runtime: Runtime, conversation_id: int) -> list[tuple[str, str]]:
    rows = runtime.db.list_recent_chat_messages_by_turns(
        int(conversation_id),
        keep_turns=max(int(runtime.settings.chat_recent_turns_to_keep or 5), 1),
    )
    history: list[tuple[str, str]] = []
    for item in rows:
        role = "human" if str(item.get("role") or "").strip().lower() == "user" else "ai"
        content = str(item.get("content") or "").strip()
        if content:
            history.append((role, content))
    return history


def _build_skill_hitl_agent_graph(runtime: Runtime, *, prompt: str, tools: list[Any]):
    if runtime.skill_agent_checkpointer is None:
        raise RuntimeError("Skill Agent checkpointer is not configured.")
    return create_agent(
        model=runtime.qwen.model,
        tools=tools,
        system_prompt=prompt,
        middleware=[
            HumanInTheLoopMiddleware(
                interrupt_on={
                    "run_command": True,
                    "write_file": True,
                    "append_file": True,
                    "make_dir": True,
                },
                description_prefix="Skill Agent 想执行文件或命令操作，请确认是否继续。",
            )
        ],
        checkpointer=runtime.skill_agent_checkpointer,
        name="skill_agent",
    )


def _build_skill_agent_config(session_id: str) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": session_id,
        }
    }


def extract_skill_agent_answer(result: dict[str, Any]) -> str:
    payload = result.value if isinstance(result, GraphOutput) else result
    messages = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(messages, list) or not messages:
        return ""
    final_message = messages[-1]
    content = getattr(final_message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content or "").strip()


async def answer_with_skill_agent(
    runtime: Runtime,
    *,
    query: str,
    conversation_id: int | None = None,
    session_id: str | None = None,
    approval_mode=None,
    actor: str = "skill-agent",
) -> dict[str, Any]:
    if runtime.skill_service is None:
        raise RuntimeError("Skill service is not available.")
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")

    result = await _execute_skill_agent_turn(
        runtime,
        query=query,
        conversation_id=conversation_id,
        session_id=session_id,
        approval_mode=approval_mode,
        actor=actor,
        event_callback=None,
    )
    return result


async def stream_answer_with_skill_agent_events(
    runtime: Runtime,
    *,
    query: str,
    conversation_id: int | None = None,
    session_id: str | None = None,
    approval_mode=None,
    actor: str = "skill-agent",
) -> AsyncIterator[str]:
    conversation = ensure_skill_agent_conversation(runtime, conversation_id)
    resolved_conversation_id = int(conversation["conversation_id"])
    resolved_session_id = build_skill_agent_session_id(
        conversation_id=resolved_conversation_id,
        explicit_session_id=session_id,
    )
    yield make_sse_event("conversation", {"conversation_id": resolved_conversation_id})
    yield make_sse_event("status", {"delta": "Skill Agent 正在准备会话上下文..."})
    if getattr(runtime, "skill_service", None) is not None:
        yield make_sse_event(
            "skills",
            {"active_skills": runtime.skill_service.get_active_skills(resolved_session_id)},
        )
    queue: asyncio.Queue[tuple[str, dict[str, Any] | None] | None] = asyncio.Queue()

    def emit_event(event_type: str, data: dict[str, Any] | None = None) -> None:
        queue.put_nowait((event_type, data or {}))

    try:
        task = asyncio.create_task(
            _execute_skill_agent_turn(
                runtime,
                query=query,
                conversation_id=resolved_conversation_id,
                session_id=session_id,
                approval_mode=approval_mode,
                actor=actor,
                event_callback=emit_event,
            )
        )
        while True:
            if task.done() and queue.empty():
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.1)
            except TimeoutError:
                continue
            if item is None:
                continue
            event_type, data = item
            yield make_sse_event(event_type, data)
        result = await task
        if result.get("status") == "pending_approval":
            yield make_sse_event(
                "approval",
                {
                    "session_id": result.get("session_id") or resolved_session_id,
                    "workspace_id": result.get("workspace_id") or "",
                    "approval_request": result.get("approval_request") or {},
                },
            )
            yield make_sse_event("skills", {"active_skills": result.get("active_skills") or []})
            yield make_sse_event("done", {})
            return
        yield make_sse_event("status", {"delta": "Skill Agent 已完成规划，正在返回结果..."})
        answer_text = str(result.get("answer") or "").strip()
        if answer_text:
            for chunk in _chunk_text(answer_text, chunk_size=48):
                yield make_sse_event("answer", {"delta": chunk})
        yield make_sse_event("skills", {"active_skills": result.get("active_skills") or []})
        yield make_sse_event("done", {})
    except Exception as exc:
        yield make_sse_event("error", {"detail": str(exc) or "Skill Agent 执行失败"})


async def _execute_skill_agent_turn(
    runtime: Runtime,
    *,
    query: str,
    conversation_id: int | None,
    session_id: str | None,
    approval_mode,
    actor: str,
    event_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    conversation = ensure_skill_agent_conversation(runtime, conversation_id)
    resolved_conversation_id = int(conversation["conversation_id"])
    resolved_session_id = build_skill_agent_session_id(
        conversation_id=resolved_conversation_id,
        explicit_session_id=session_id,
    )
    workspace = ensure_skill_agent_workspace(runtime, conversation_id=resolved_conversation_id, actor=actor)
    history = build_skill_agent_history(runtime, resolved_conversation_id)

    runtime.db.append_chat_message(
        resolved_conversation_id,
        role="user",
        content=query,
    )
    if event_callback is not None:
        event_callback("status", {"delta": "Skill Agent 正在加载 skills 与 workspace tools..."})

    skill_tools = build_skill_langchain_tools(
        runtime.skill_service,
        session_id=resolved_session_id,
        actor=actor,
        event_callback=event_callback,
    )
    workspace_tools = build_langchain_tools(
        runtime.tool_service,
        workspace_id=workspace["workspace_id"],
        actor=actor,
        approval_mode=approval_mode,
        event_callback=event_callback,
    )
    prompt = build_skill_agent_prompt(
        runtime,
        session_id=resolved_session_id,
        workspace_id=workspace["workspace_id"],
    )

    graph = _build_skill_hitl_agent_graph(
        runtime,
        prompt=prompt,
        tools=[*skill_tools, *workspace_tools],
    )
    if event_callback is not None:
        event_callback("status", {"delta": "Skill Agent 正在思考并决定下一步..."})
    result = await graph.ainvoke(
        {
            "messages": [
                *history,
                ("human", query),
            ]
        },
        config=_build_skill_agent_config(resolved_session_id),
        version="v2",
    )
    if result.interrupts:
        if event_callback is not None:
            event_callback("status", {"delta": "Skill Agent 需要人工确认后才能继续。"})
        return {
            "status": "pending_approval",
            "conversation_id": resolved_conversation_id,
            "session_id": resolved_session_id,
            "workspace_id": workspace["workspace_id"],
            "approval_request": _format_interrupt(runtime, result.interrupts[0]),
            "active_skills": runtime.skill_service.get_active_skills(resolved_session_id),
        }

    answer_text = extract_skill_agent_answer(result)
    if not answer_text:
        answer_text = "当前没有生成有效回答。"
    if event_callback is not None:
        event_callback("status", {"delta": "Skill Agent 已生成最终回答。"})

    assistant_message = runtime.db.append_chat_message(
        resolved_conversation_id,
        role="assistant",
        content=answer_text,
    )

    return {
        "status": "completed",
        "conversation_id": resolved_conversation_id,
        "session_id": resolved_session_id,
        "workspace_id": workspace["workspace_id"],
        "answer": answer_text,
        "assistant_message": assistant_message,
        "active_skills": runtime.skill_service.get_active_skills(resolved_session_id),
    }


async def resume_skill_agent_turn(
    runtime: Runtime,
    *,
    session_id: str,
    decision: dict[str, Any],
    conversation_id: int | None = None,
    actor: str = "skill-agent",
) -> dict[str, Any]:
    if runtime.skill_service is None:
        raise RuntimeError("Skill service is not available.")
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")

    normalized_conversation_id = int(conversation_id) if conversation_id else None
    if normalized_conversation_id is None and str(session_id).startswith("conversation-"):
        try:
            normalized_conversation_id = int(str(session_id).split("-", 1)[1])
        except ValueError:
            normalized_conversation_id = None
    if normalized_conversation_id is None:
        raise RuntimeError("conversation_id is required to resume the skill agent.")

    conversation = ensure_skill_agent_conversation(runtime, normalized_conversation_id)
    resolved_conversation_id = int(conversation["conversation_id"])
    workspace = ensure_skill_agent_workspace(runtime, conversation_id=resolved_conversation_id, actor=actor)
    prompt = build_skill_agent_prompt(
        runtime,
        session_id=session_id,
        workspace_id=workspace["workspace_id"],
    )
    graph = _build_skill_hitl_agent_graph(
        runtime,
        prompt=prompt,
        tools=[
            *build_skill_langchain_tools(runtime.skill_service, session_id=session_id, actor=actor),
            *build_langchain_tools(runtime.tool_service, workspace_id=workspace["workspace_id"], actor=actor),
        ],
    )
    result = await graph.ainvoke(
        Command(resume={"decisions": [decision]}),
        config=_build_skill_agent_config(session_id),
        version="v2",
    )
    if result.interrupts:
        return {
            "status": "pending_approval",
            "conversation_id": resolved_conversation_id,
            "session_id": session_id,
            "workspace_id": workspace["workspace_id"],
            "approval_request": _format_interrupt(runtime, result.interrupts[0]),
            "active_skills": runtime.skill_service.get_active_skills(session_id),
        }

    answer_text = extract_skill_agent_answer(result)
    if not answer_text:
        answer_text = "当前没有生成有效回答。"
    assistant_message = runtime.db.append_chat_message(
        resolved_conversation_id,
        role="assistant",
        content=answer_text,
    )
    return {
        "status": "completed",
        "conversation_id": resolved_conversation_id,
        "session_id": session_id,
        "workspace_id": workspace["workspace_id"],
        "answer": answer_text,
        "assistant_message": assistant_message,
        "active_skills": runtime.skill_service.get_active_skills(session_id),
    }


async def stream_resume_skill_agent_turn_events(
    runtime: Runtime,
    *,
    session_id: str,
    decision: dict[str, Any],
    conversation_id: int | None = None,
    actor: str = "skill-agent",
) -> AsyncIterator[str]:
    normalized_conversation_id = int(conversation_id) if conversation_id else None
    if normalized_conversation_id is None and str(session_id).startswith("conversation-"):
        try:
            normalized_conversation_id = int(str(session_id).split("-", 1)[1])
        except ValueError:
            normalized_conversation_id = None
    if normalized_conversation_id is None:
        raise RuntimeError("conversation_id is required to resume the skill agent.")

    yield make_sse_event("conversation", {"conversation_id": normalized_conversation_id})
    yield make_sse_event("status", {"delta": "Skill Agent 正在恢复执行..."})
    if getattr(runtime, "skill_service", None) is not None:
        yield make_sse_event("skills", {"active_skills": runtime.skill_service.get_active_skills(session_id)})

    queue: asyncio.Queue[tuple[str, dict[str, Any] | None] | None] = asyncio.Queue()

    def emit_event(event_type: str, data: dict[str, Any] | None = None) -> None:
        queue.put_nowait((event_type, data or {}))

    async def run() -> dict[str, Any]:
        conversation = ensure_skill_agent_conversation(runtime, normalized_conversation_id)
        resolved_conversation_id = int(conversation["conversation_id"])
        workspace = ensure_skill_agent_workspace(runtime, conversation_id=resolved_conversation_id, actor=actor)
        prompt = build_skill_agent_prompt(
            runtime,
            session_id=session_id,
            workspace_id=workspace["workspace_id"],
        )
        graph = _build_skill_hitl_agent_graph(
            runtime,
            prompt=prompt,
            tools=[
                *build_skill_langchain_tools(
                    runtime.skill_service,
                    session_id=session_id,
                    actor=actor,
                    event_callback=emit_event,
                ),
                *build_langchain_tools(
                    runtime.tool_service,
                    workspace_id=workspace["workspace_id"],
                    actor=actor,
                    event_callback=emit_event,
                ),
            ],
        )
        emit_event("status", {"delta": "Skill Agent 已接收审批结果，继续执行..."})
        result = await graph.ainvoke(
            Command(resume={"decisions": [decision]}),
            config=_build_skill_agent_config(session_id),
            version="v2",
        )
        if result.interrupts:
            emit_event("status", {"delta": "Skill Agent 需要新的人工确认。"})
            return {
                "status": "pending_approval",
                "conversation_id": resolved_conversation_id,
                "session_id": session_id,
                "workspace_id": workspace["workspace_id"],
                "approval_request": _format_interrupt(runtime, result.interrupts[0]),
                "active_skills": runtime.skill_service.get_active_skills(session_id),
            }

        answer_text = extract_skill_agent_answer(result) or "当前没有生成有效回答。"
        runtime.db.append_chat_message(
            resolved_conversation_id,
            role="assistant",
            content=answer_text,
        )
        emit_event("status", {"delta": "Skill Agent 已生成最终回答。"})
        return {
            "status": "completed",
            "conversation_id": resolved_conversation_id,
            "session_id": session_id,
            "workspace_id": workspace["workspace_id"],
            "answer": answer_text,
            "active_skills": runtime.skill_service.get_active_skills(session_id),
        }

    try:
        task = asyncio.create_task(run())
        while True:
            if task.done() and queue.empty():
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.1)
            except TimeoutError:
                continue
            if item is None:
                continue
            event_type, data = item
            yield make_sse_event(event_type, data)
        result = await task
        if result.get("status") == "pending_approval":
            yield make_sse_event(
                "approval",
                {
                    "session_id": result.get("session_id") or session_id,
                    "workspace_id": result.get("workspace_id") or "",
                    "approval_request": result.get("approval_request") or {},
                },
            )
            yield make_sse_event("skills", {"active_skills": result.get("active_skills") or []})
            yield make_sse_event("done", {})
            return
        answer_text = str(result.get("answer") or "").strip()
        if answer_text:
            for chunk in _chunk_text(answer_text, chunk_size=48):
                yield make_sse_event("answer", {"delta": chunk})
        yield make_sse_event("skills", {"active_skills": result.get("active_skills") or []})
        yield make_sse_event("done", {})
    except Exception as exc:
        yield make_sse_event("error", {"detail": str(exc) or "Skill Agent 恢复执行失败"})


def _chunk_text(text: str, *, chunk_size: int = 64) -> list[str]:
    payload = str(text or "")
    if not payload:
        return []
    safe_chunk_size = max(int(chunk_size), 1)
    return [payload[index : index + safe_chunk_size] for index in range(0, len(payload), safe_chunk_size)]


def _format_interrupt(runtime: Runtime, interrupt: Interrupt) -> dict[str, Any]:
    value = interrupt.value if isinstance(interrupt, Interrupt) else {}
    payload = value if isinstance(value, dict) else {}
    action_requests = []
    for item in list(payload.get("action_requests") or []):
        action = dict(item or {})
        tool_policy = getattr(runtime.tool_service, "policy", None) if runtime.tool_service is not None else None
        if action.get("name") == "run_command" and tool_policy is not None:
            decision = evaluate_command_request(
                tool_policy,
                str((action.get("args") or {}).get("command") or ""),
            )
            action["policy_allowed"] = bool(decision.allowed)
            action["policy_requires_approval"] = bool(decision.requires_approval)
            action["policy_reason"] = decision.reason
            action["policy_blocked"] = not bool(decision.allowed)
        else:
            action["policy_allowed"] = True
            action["policy_requires_approval"] = False
            action["policy_reason"] = ""
            action["policy_blocked"] = False
        action_requests.append(action)
    return {
        "interrupt_id": getattr(interrupt, "id", ""),
        "action_requests": action_requests,
        "review_configs": list(payload.get("review_configs") or []),
    }
