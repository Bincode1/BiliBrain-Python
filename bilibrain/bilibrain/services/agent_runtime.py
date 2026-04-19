from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from bilibrain.core.runtime import Runtime
from bilibrain.graphs.qa.events import make_sse_event
from bilibrain.services.chat_storage import (
    append_chat_message_dual_write,
    create_chat_session_dual_write,
    get_chat_session,
    list_recent_chat_session_messages,
    read_chat_session_pending_approval,
)
from bilibrain.services.runtime_events import (
    build_persisting_runtime_event_callback,
    clear_pending_approval_state,
    persist_pending_approval_state,
    persist_runtime_event,
)
from bilibrain.skills import build_skill_langchain_tools
from bilibrain.tools import build_langchain_tools
from bilibrain.tools.policy import evaluate_command_request


# Tools that require HITL approval before execution
_HITL_TOOLS = {"run_command", "write_file", "append_file", "make_dir"}
_MAX_ROUNDS = 20


def _build_skills_state(runtime: Runtime, session_id: str) -> dict[str, Any]:
    if runtime.skill_service is None:
        return {"active_skills": [], "loaded_skills": []}
    return {
        "active_skills": runtime.skill_service.get_active_skills(session_id),
        "loaded_skills": runtime.skill_service.get_loaded_skills(session_id),
    }


def _current_action_from_request(approval_request: dict[str, Any] | None) -> dict[str, Any]:
    actions = approval_request.get("action_requests") if isinstance(approval_request, dict) else None
    if not isinstance(actions, list) or not actions:
        raise RuntimeError("当前审批请求缺少可执行操作。")
    action = actions[0]
    if not isinstance(action, dict):
        raise RuntimeError("当前审批请求格式无效。")
    return dict(action)


def _merge_decision_args(action: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    merged = dict(action.get("args") or {})
    decision_args = decision.get("args")
    if isinstance(decision_args, dict):
        merged.update(decision_args)
    return merged


def _normalize_resume_decision(
    approval_request: dict[str, Any],
    decision: dict[str, Any],
) -> tuple[str, dict[str, Any], str, dict[str, Any]]:
    action = _current_action_from_request(approval_request)
    action_name = str(action.get("name") or "").strip()
    action_id = str(action.get("id") or approval_request.get("interrupt_id") or "").strip()
    if not action_name or not action_id:
        raise RuntimeError("当前审批请求缺少必要标识。")

    decision_type = str(decision.get("type") or "").strip().lower() or "approve"
    if decision_type not in {"approve", "edit", "reject"}:
        raise RuntimeError("审批结果无效。")

    if decision_type in {"approve", "edit"}:
        decision_name = str(decision.get("name") or action_name).strip()
        decision_id = str(decision.get("id") or action_id).strip()
        if decision_name != action_name or decision_id != action_id:
            raise RuntimeError("审批操作与当前待处理请求不一致。")

    return decision_type, action, action_id, _merge_decision_args(action, decision)


async def _persist_pending_approval(
    runtime: Runtime,
    *,
    conversation_id: int,
    session_id: str,
    workspace_id: str,
    approval_request: dict[str, Any],
) -> dict[str, Any]:
    return await persist_pending_approval_state(
        runtime,
        conversation_id=int(conversation_id),
        session_id=session_id,
        workspace_id=workspace_id,
        approval_request=approval_request,
    )


async def _load_pending_approval(
    runtime: Runtime,
    *,
    conversation_id: int,
    session_id: str,
) -> dict[str, Any]:
    payload = await read_chat_session_pending_approval(runtime, conversation_id)
    if not payload:
        raise RuntimeError("当前没有待审批的操作。")
    saved_session_id = str(payload.get("session_id") or "").strip()
    if saved_session_id and saved_session_id != str(session_id).strip():
        raise RuntimeError("审批会话已失效，请重新发起操作。")
    return payload


async def _consume_pending_approval(
    runtime: Runtime,
    *,
    conversation_id: int,
    session_id: str,
    decision: dict[str, Any],
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    pending = await _load_pending_approval(
        runtime,
        conversation_id=conversation_id,
        session_id=session_id,
    )
    approval_request = dict(pending.get("approval_request") or {})
    decision_type, action, action_id, effective_args = _normalize_resume_decision(
        approval_request,
        decision,
    )
    await clear_pending_approval_state(
        runtime,
        conversation_id=int(conversation_id),
        workspace_id=str(pending.get("workspace_id") or "default"),
    )
    await persist_runtime_event(
        runtime,
        conversation_id=int(conversation_id),
        workspace_id=str(pending.get("workspace_id") or "default"),
        event_type="approval",
        payload={
            "phase": decision_type,
            "name": str(action.get("name") or ""),
            "approval_id": action_id,
            "session_id": session_id,
            "workspace_id": str(pending.get("workspace_id") or ""),
            "original_args": dict(action.get("args") or {}),
            "effective_args": effective_args,
        },
    )
    return pending, decision_type, action, effective_args


def _summarize_tool_result_answer(
    tool_name: str,
    effective_args: dict[str, Any],
    result_str: str,
    fallback: str,
) -> str:
    try:
        payload = json.loads(result_str)
    except json.JSONDecodeError:
        return fallback
    if not isinstance(payload, dict):
        return fallback

    if payload.get("error"):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail") or str(error)
        else:
            message = str(error)
        return message or fallback

    result_payload = payload.get("payload")
    if not isinstance(result_payload, dict):
        return fallback

    if tool_name == "write_file":
        path = str(result_payload.get("path") or effective_args.get("path") or "").strip()
        return f"文件 `{path}` 已成功创建。"
    if tool_name == "append_file":
        path = str(result_payload.get("path") or effective_args.get("path") or "").strip()
        return f"内容已成功追加到文件 `{path}`。"
    if tool_name == "make_dir":
        path = str(result_payload.get("path") or effective_args.get("path") or "").strip()
        return f"目录 `{path}` 已成功创建。"
    if tool_name == "run_command":
        return "命令已执行完成。"
    return fallback


async def _flush_persisted_event_tasks(tasks: list[asyncio.Task[None]]) -> None:
    if not tasks:
        return
    pending = [task for task in tasks if not task.done()]
    if pending:
        await asyncio.gather(*pending)


def _build_persisting_event_callback(
    runtime: Runtime,
    *,
    conversation_id: int,
    workspace_id: str,
    downstream: Callable[[str, dict[str, Any]], None] | None,
    tasks: list[asyncio.Task[None]],
) -> Callable[[str, dict[str, Any]], None]:
    return build_persisting_runtime_event_callback(
        runtime,
        conversation_id=int(conversation_id),
        workspace_id=str(workspace_id or "default"),
        downstream=downstream,
        tasks=tasks,
    )


def build_agent_session_id(
    *, conversation_id: int | None = None, explicit_session_id: str | None = None
) -> str:
    explicit = str(explicit_session_id or "").strip()
    if explicit:
        return explicit
    if conversation_id:
        return f"conversation-{int(conversation_id)}"
    raise RuntimeError(
        "session_id is required when conversation_id is not provided."
    )


def build_agent_prompt(
    runtime: Runtime,
    *,
    session_id: str,
    workspace_id: str,
    actor: str,
) -> str:
    available_skills = (
        runtime.skill_service.build_available_skills_prompt(session_id=session_id, actor=actor)
        if runtime.skill_service
        else "<available_skills />"
    )
    tools = runtime.tool_service.list_tools() if runtime.tool_service else []
    tool_lines = []
    for item in tools:
        if not item.get("enabled", True):
            continue
        tool_lines.append(f"- {item['name']}: {item['description']}")
    tool_block = "\n".join(tool_lines) if tool_lines else "- 当前没有可用工具"

    return "\n".join(
        [
            "你是 BiliBrain 的 Agent。",
            "你的职责是结合会话上下文、可用 skills 和 workspace tools 来完成任务。",
            "原则：",
            "1. prompt 里只提供已激活 skills 的摘要，不提供正文。",
            "2. <access> 为 allow 的 skill 可以直接调用 skill(name)；<access> 为 ask 的 skill 需要先走审批。",
            "3. 只有当任务明显匹配某个 skill 时，才调用 skill(name) 读取完整 SKILL.md。",
            "4. skill(name) 返回正文后，再依据其中的说明继续处理。",
            "5. skill(name) 会返回 BILIBRAIN_SKILL_DIR、resource_map 和 usage_rules；相对路径默认相对 BILIBRAIN_SKILL_DIR 解析。",
            "6. 如果 skill 正文提到 references、scripts、assets 或其他文件，不要假设内容已加载，继续用普通工具按需读取或执行。",
            "7. 对文件和命令操作保持克制，只在当前 workspace 内工作。",
            "8. 如果工具或 skill 因审批策略失败，要明确告诉用户需要预批准，而不是伪造执行结果。",
            "9. 不要调用不存在的 activate_skill；skills 由用户预先激活，你运行时只负责读取。",
            "",
            f"当前 workspace_id: {workspace_id}",
            "",
            "当前可用工具：",
            tool_block,
            "",
            "当前可用 skills 摘要：",
            available_skills,
        ]
    )


async def get_or_create_conversation(
    runtime: Runtime, conversation_id: int | None
) -> dict[str, Any]:
    if conversation_id:
        conversation = await get_chat_session(runtime, int(conversation_id))
        if not conversation:
            raise RuntimeError("对话会话不存在，请刷新页面后重试。")
        return conversation
    return await create_chat_session_dual_write(runtime, folder_id=None, title="")


async def get_default_workspace(
    runtime: Runtime, *, actor: str
) -> dict[str, Any]:
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")
    return await runtime.tool_service.get_or_create_default_workspace(actor=actor)


async def build_agent_history(
    runtime: Runtime, conversation_id: int
) -> list[tuple[str, str]]:
    rows = await list_recent_chat_session_messages(
        runtime,
        int(conversation_id),
        keep_turns=max(int(runtime.settings.chat_recent_turns_to_keep or 5), 1),
    )
    history: list[tuple[str, str]] = []
    for item in rows:
        role = (
            "human" if str(item.get("role") or "").strip().lower() == "user" else "ai"
        )
        content = str(item.get("content") or "").strip()
        if content:
            history.append((role, content))
    return history


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

def _build_tool_executor(
    tools: list[Any],
    *,
    runtime: Runtime,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
):
    tool_map: dict[str, Any] = {}
    for t in tools:
        name = getattr(t, "name", None) or getattr(t, "func", None).__name__
        tool_map[name] = t

    async def execute(name: str, arguments: dict[str, Any]) -> str:
        t = tool_map.get(name)
        if t is None:
            return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
        try:
            result = await t.ainvoke(arguments)
        except Exception as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False)
        return str(result)

    return tool_map, execute


def _build_approval_request(
    runtime: Runtime,
    tool_name: str,
    tool_args: dict[str, Any],
    call_id: str,
) -> dict[str, Any]:
    action: dict[str, Any] = {
        "name": tool_name,
        "args": tool_args,
        "id": call_id,
    }
    tool_policy = (
        getattr(runtime.tool_service, "policy", None)
        if runtime.tool_service is not None
        else None
    )
    if tool_name == "run_command" and tool_policy is not None:
        decision = evaluate_command_request(
            tool_policy,
            str((tool_args or {}).get("command") or ""),
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

    return {
        "interrupt_id": call_id,
        "action_requests": [action],
        "review_configs": [],
    }


def _build_skill_approval_request(
    runtime: Runtime,
    *,
    skill_name: str,
    call_id: str,
    session_id: str,
    actor: str,
) -> dict[str, Any]:
    skill_service = runtime.skill_service
    if skill_service is None:
        raise RuntimeError("Skill service is not available.")
    decision = skill_service.evaluate_skill_access(
        name=skill_name,
        session_id=session_id,
        actor=actor,
    )
    skill_detail = skill_service.get_skill(name=skill_name)
    return {
        "interrupt_id": call_id,
        "action_requests": [
            {
                "name": "skill",
                "args": {"name": skill_name},
                "id": call_id,
                "description": f"技能 '{skill_name}' 需要审批后才能加载完整 SKILL.md。",
                "summary": {
                    "skill_name": skill_name,
                    "description": skill_detail.get("description") or "",
                    "resource_count": len(skill_detail.get("resources") or []),
                    "allowed_tools": skill_detail.get("allowed_tools") or [],
                    "access": decision.action.value,
                },
                "policy_allowed": True,
                "policy_requires_approval": bool(decision.requires_approval),
                "policy_reason": decision.reason,
                "policy_blocked": False,
            }
        ],
        "review_configs": [
            {
                "action_name": "skill",
                "allowed_decisions": ["approve", "edit", "reject"],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Core agent loop (non-streaming)
# ---------------------------------------------------------------------------

async def _run_agent_loop(
    runtime: Runtime,
    *,
    messages: list[Any],
    tools: list[Any],
    session_id: str,
    actor: str,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    llm = runtime.qwen.model.bind_tools(tools)
    _, execute = _build_tool_executor(tools, runtime=runtime, event_callback=event_callback)

    for _round in range(_MAX_ROUNDS):
        if event_callback is not None:
            event_callback("status", {"delta": "Agent 正在思考并决定下一步..."})

        response = await llm.ainvoke(messages)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            content = response.content or ""
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = str(item.get("text") or "").strip()
                        if text:
                            parts.append(text)
                content = "\n".join(parts)
            return str(content).strip(), None

        messages.append(response)

        for tc in tool_calls:
            tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")

            if tc_name in _HITL_TOOLS:
                approval_request = _build_approval_request(runtime, tc_name, tc_args, tc_id)
                return "", approval_request

            if tc_name == "skill":
                skill_name = str((tc_args or {}).get("name") or "").strip()
                decision = runtime.skill_service.evaluate_skill_access(
                    name=skill_name,
                    session_id=session_id,
                    actor=actor,
                ) if runtime.skill_service is not None else None
                if decision is not None and decision.requires_approval:
                    if event_callback is not None:
                        event_callback(
                            "skill",
                            {
                                "phase": "approval_required",
                                "name": skill_name,
                                "session_id": session_id,
                                "error": decision.reason,
                            },
                        )
                    approval_request = _build_skill_approval_request(
                        runtime,
                        skill_name=skill_name,
                        call_id=tc_id,
                        session_id=session_id,
                        actor=actor,
                    )
                    return "", approval_request

            if event_callback is not None:
                event_callback("tool", {"phase": "start", "name": tc_name, "summary": {}})

            result_str = await execute(tc_name, tc_args)

            if event_callback is not None:
                event_callback("tool", {
                    "phase": "finish", "name": tc_name,
                    "ok": '"error"' not in result_str[:80],
                })

            messages.append(ToolMessage(content=result_str, tool_call_id=tc_id))

    return "已达最大推理轮次，请精简问题后重试。", None


# ---------------------------------------------------------------------------
# Non-streaming entry
# ---------------------------------------------------------------------------

async def answer_with_agent_runtime(
    runtime: Runtime,
    *,
    query: str,
    conversation_id: int | None = None,
    session_id: str | None = None,
    approval_mode=None,
    actor: str = "agent",
) -> dict[str, Any]:
    if runtime.skill_service is None:
        raise RuntimeError("Skill service is not available.")
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")

    result = await _execute_agent_turn(
        runtime,
        query=query,
        conversation_id=conversation_id,
        session_id=session_id,
        approval_mode=approval_mode,
        actor=actor,
        event_callback=None,
    )
    return result


async def _execute_agent_turn(
    runtime: Runtime,
    *,
    query: str,
    conversation_id: int | None,
    session_id: str | None,
    approval_mode,
    actor: str,
    event_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    persisted_event_tasks: list[asyncio.Task[None]] = []
    try:
        conversation = await get_or_create_conversation(runtime, conversation_id)
        resolved_conversation_id = int(conversation["conversation_id"])
        resolved_session_id = build_agent_session_id(
            conversation_id=resolved_conversation_id,
            explicit_session_id=session_id,
        )
        workspace = await get_default_workspace(runtime, actor=actor)
        persisted_event_callback = _build_persisting_event_callback(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=workspace["workspace_id"],
            downstream=event_callback,
            tasks=persisted_event_tasks,
        )
        history = await build_agent_history(runtime, resolved_conversation_id)

        await append_chat_message_dual_write(
            runtime,
            resolved_conversation_id,
            role="user",
            content=query,
        )
        if event_callback is not None:
            event_callback(
                "status", {"delta": "Agent 正在加载 skills 与 workspace tools..."}
            )

        skill_tools = build_skill_langchain_tools(
            runtime.skill_service,
            session_id=resolved_session_id,
            actor=actor,
            event_callback=persisted_event_callback,
        )
        workspace_tools = build_langchain_tools(
            runtime.tool_service,
            workspace_id=workspace["workspace_id"],
            actor=actor,
            approval_mode=approval_mode,
            event_callback=persisted_event_callback,
        )
        all_tools = [*skill_tools, *workspace_tools]
        prompt = build_agent_prompt(
            runtime,
            session_id=resolved_session_id,
            workspace_id=workspace["workspace_id"],
            actor=actor,
        )

        messages: list[Any] = [SystemMessage(content=prompt)]
        for role, content in history:
            if role == "human":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))
        messages.append(HumanMessage(content=query))

        answer_text, approval_request = await _run_agent_loop(
            runtime,
            messages=messages,
            tools=all_tools,
            session_id=resolved_session_id,
            actor=actor,
            event_callback=persisted_event_callback,
        )

        if approval_request is not None:
            await _persist_pending_approval(
                runtime,
                conversation_id=resolved_conversation_id,
                session_id=resolved_session_id,
                workspace_id=workspace["workspace_id"],
                approval_request=approval_request,
            )
            if event_callback is not None:
                event_callback("status", {"delta": "Agent 需要人工确认后才能继续。"})
            return {
                "status": "pending_approval",
                "conversation_id": resolved_conversation_id,
                "session_id": resolved_session_id,
                "workspace_id": workspace["workspace_id"],
                "approval_request": approval_request,
                **_build_skills_state(runtime, resolved_session_id),
            }

        await clear_pending_approval_state(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=str(workspace["workspace_id"] or "default"),
        )
        if not answer_text:
            answer_text = "当前没有生成有效回答。"
        if event_callback is not None:
            event_callback("status", {"delta": "Agent 已生成最终回答。"})

        assistant_message = await append_chat_message_dual_write(
            runtime,
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
            **_build_skills_state(runtime, resolved_session_id),
        }
    finally:
        await _flush_persisted_event_tasks(persisted_event_tasks)


# ---------------------------------------------------------------------------
# Streaming entry
# ---------------------------------------------------------------------------

async def stream_agent_events(
    runtime: Runtime,
    *,
    query: str,
    conversation_id: int | None = None,
    session_id: str | None = None,
    approval_mode=None,
    actor: str = "agent",
) -> AsyncIterator[str]:
    persisted_event_tasks: list[asyncio.Task[None]] = []
    conversation = await get_or_create_conversation(runtime, conversation_id)
    resolved_conversation_id = int(conversation["conversation_id"])
    resolved_session_id = build_agent_session_id(
        conversation_id=resolved_conversation_id,
        explicit_session_id=session_id,
    )
    yield make_sse_event("conversation", {"conversation_id": resolved_conversation_id})
    yield make_sse_event("status", {"delta": "Agent 正在准备会话上下文..."})
    if getattr(runtime, "skill_service", None) is not None:
        yield make_sse_event(
            "skills",
            _build_skills_state(runtime, resolved_session_id),
        )
    queue: asyncio.Queue[tuple[str, dict[str, Any] | None] | None] = asyncio.Queue()

    def emit_event(event_type: str, data: dict[str, Any] | None = None) -> None:
        queue.put_nowait((event_type, data or {}))

    try:
        task = asyncio.create_task(
            _execute_agent_turn(
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
            yield make_sse_event("skills", {
                "active_skills": result.get("active_skills") or [],
                "loaded_skills": result.get("loaded_skills") or [],
            })
            yield make_sse_event("done", {})
            return
        await clear_pending_approval_state(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=str(result.get("workspace_id") or "default"),
        )
        yield make_sse_event(
            "status", {"delta": "Agent 已完成规划，正在返回结果..."}
        )
        answer_text = str(result.get("answer") or "").strip()
        if answer_text:
            for chunk in _chunk_text(answer_text, chunk_size=48):
                yield make_sse_event("answer", {"delta": chunk})
        yield make_sse_event("skills", {
            "active_skills": result.get("active_skills") or [],
            "loaded_skills": result.get("loaded_skills") or [],
        })
        yield make_sse_event("done", {})
    except Exception as exc:
        yield make_sse_event("error", {"detail": str(exc) or "Agent 执行失败"})
    finally:
        await _flush_persisted_event_tasks(persisted_event_tasks)


# ---------------------------------------------------------------------------
# Resume (HITL)
# ---------------------------------------------------------------------------

def _resolve_conversation_id(
    session_id: str, conversation_id: int | None
) -> int:
    normalized = int(conversation_id) if conversation_id else None
    if normalized is None and str(session_id).startswith("conversation-"):
        try:
            normalized = int(str(session_id).split("-", 1)[1])
        except ValueError:
            pass
    if normalized is None:
        raise RuntimeError("conversation_id is required to resume the agent.")
    return normalized


async def resume_agent_turn(
    runtime: Runtime,
    *,
    session_id: str,
    decision: dict[str, Any],
    conversation_id: int | None = None,
    actor: str = "agent",
) -> dict[str, Any]:
    persisted_event_tasks: list[asyncio.Task[None]] = []
    if runtime.skill_service is None:
        raise RuntimeError("Skill service is not available.")
    if runtime.tool_service is None:
        raise RuntimeError("Tool service is not available.")

    try:
        resolved_conversation_id = _resolve_conversation_id(session_id, conversation_id)
        conversation = await get_or_create_conversation(runtime, resolved_conversation_id)
        resolved_conversation_id = int(conversation["conversation_id"])
        pending, decision_type, action, effective_args = await _consume_pending_approval(
            runtime,
            conversation_id=resolved_conversation_id,
            session_id=session_id,
            decision=decision,
        )
        persisted_event_callback = _build_persisting_event_callback(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=str(pending.get("workspace_id") or "default"),
            downstream=None,
            tasks=persisted_event_tasks,
        )
        workspace = await get_default_workspace(runtime, actor=actor)
        workspace_id = str(pending.get("workspace_id") or workspace["workspace_id"])

        prompt = build_agent_prompt(
            runtime, session_id=session_id, workspace_id=workspace_id, actor=actor,
        )
        skill_tools = build_skill_langchain_tools(
            runtime.skill_service, session_id=session_id, actor=actor,
            event_callback=persisted_event_callback,
        )
        langchain_tools = build_langchain_tools(
            runtime.tool_service, workspace_id=workspace_id, actor=actor,
            event_callback=persisted_event_callback,
        )
        all_tools = [*skill_tools, *langchain_tools]
        _, execute = _build_tool_executor(
            all_tools, runtime=runtime, event_callback=persisted_event_callback,
        )

        history = await build_agent_history(runtime, resolved_conversation_id)
        messages: list[Any] = [SystemMessage(content=prompt)]
        for role, content in history:
            if role == "human":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        approved_name = str(action.get("name") or "")
        approved_args = effective_args
        approved_id = str(action.get("id") or f"resume-{approved_name}")

        messages.append(AIMessage(
            content="",
            tool_calls=[{"name": approved_name, "args": approved_args, "id": approved_id}],
        ))
        if decision_type == "reject":
            answer_text = str(decision.get("message") or "用户拒绝了当前操作。").strip()
            assistant_message = await append_chat_message_dual_write(
                runtime,
                resolved_conversation_id,
                role="assistant",
                content=answer_text,
            )
            return {
                "status": "completed",
                "conversation_id": resolved_conversation_id,
                "session_id": session_id,
                "workspace_id": workspace_id,
                "answer": answer_text,
                "assistant_message": assistant_message,
                **_build_skills_state(runtime, session_id),
            }
        if approved_name == "skill" and runtime.skill_service is not None:
            runtime.skill_service.approve_skill(
                name=str(approved_args.get("name") or ""),
                session_id=session_id,
            )

        result_str = await execute(approved_name, approved_args)
        messages.append(ToolMessage(content=result_str, tool_call_id=approved_id))

        answer_text, next_approval = await _run_agent_loop(
            runtime,
            messages=messages,
            tools=all_tools,
            session_id=session_id,
            actor=actor,
            event_callback=persisted_event_callback,
        )

        if next_approval is not None:
            await _persist_pending_approval(
                runtime,
                conversation_id=resolved_conversation_id,
                session_id=session_id,
                workspace_id=workspace_id,
                approval_request=next_approval,
            )
            return {
                "status": "pending_approval",
                "conversation_id": resolved_conversation_id,
                "session_id": session_id,
                "workspace_id": workspace_id,
                "approval_request": next_approval,
                **_build_skills_state(runtime, session_id),
            }

        if not answer_text:
            answer_text = "当前没有生成有效回答。"
        answer_text = _summarize_tool_result_answer(
            approved_name,
            approved_args,
            result_str,
            answer_text,
        )
        assistant_message = await append_chat_message_dual_write(
            runtime,
            resolved_conversation_id,
            role="assistant",
            content=answer_text,
        )
        return {
            "status": "completed",
            "conversation_id": resolved_conversation_id,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "answer": answer_text,
            "assistant_message": assistant_message,
            **_build_skills_state(runtime, session_id),
        }
    finally:
        await _flush_persisted_event_tasks(persisted_event_tasks)


async def stream_resume_agent_events(
    runtime: Runtime,
    *,
    session_id: str,
    decision: dict[str, Any],
    conversation_id: int | None = None,
    actor: str = "agent",
) -> AsyncIterator[str]:
    persisted_event_tasks: list[asyncio.Task[None]] = []
    normalized_conversation_id = _resolve_conversation_id(session_id, conversation_id)

    yield make_sse_event(
        "conversation", {"conversation_id": normalized_conversation_id}
    )
    yield make_sse_event("status", {"delta": "Agent 正在恢复执行..."})
    if runtime.skill_service is not None:
        yield make_sse_event(
            "skills",
            _build_skills_state(runtime, session_id),
        )

    queue: asyncio.Queue[tuple[str, dict[str, Any] | None] | None] = asyncio.Queue()

    def emit_event(event_type: str, data: dict[str, Any] | None = None) -> None:
        queue.put_nowait((event_type, data or {}))

    async def run() -> dict[str, Any]:
        conversation = await get_or_create_conversation(runtime, normalized_conversation_id)
        resolved_conversation_id = int(conversation["conversation_id"])
        pending, decision_type, action, effective_args = await _consume_pending_approval(
            runtime,
            conversation_id=resolved_conversation_id,
            session_id=session_id,
            decision=decision,
        )
        workspace = await get_default_workspace(runtime, actor=actor)
        workspace_id = str(pending.get("workspace_id") or workspace["workspace_id"])
        persisted_event_callback = _build_persisting_event_callback(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=workspace_id,
            downstream=emit_event,
            tasks=persisted_event_tasks,
        )

        prompt = build_agent_prompt(
            runtime, session_id=session_id, workspace_id=workspace_id, actor=actor,
        )
        skill_tools = build_skill_langchain_tools(
            runtime.skill_service, session_id=session_id, actor=actor,
            event_callback=persisted_event_callback,
        )
        langchain_tools = build_langchain_tools(
            runtime.tool_service, workspace_id=workspace_id, actor=actor,
            event_callback=persisted_event_callback,
        )
        all_tools = [*skill_tools, *langchain_tools]
        _, execute = _build_tool_executor(
            all_tools, runtime=runtime, event_callback=persisted_event_callback,
        )

        history = await build_agent_history(runtime, resolved_conversation_id)
        messages: list[Any] = [SystemMessage(content=prompt)]
        for role, content in history:
            if role == "human":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        # Inject approved tool call
        approved_name = str(action.get("name") or "")
        approved_args = effective_args
        approved_id = str(action.get("id") or f"resume-{approved_name}")

        messages.append(AIMessage(
            content="",
            tool_calls=[{"name": approved_name, "args": approved_args, "id": approved_id}],
        ))
        if decision_type == "reject":
            answer_text = str(decision.get("message") or "用户拒绝了当前操作。").strip()
            await append_chat_message_dual_write(
                runtime,
                resolved_conversation_id,
                role="assistant",
                content=answer_text,
            )
            emit_event("status", {"delta": "用户拒绝了当前操作。"})
            return {
                "status": "completed",
                "conversation_id": resolved_conversation_id,
                "session_id": session_id,
                "workspace_id": workspace_id,
                "answer": answer_text,
                **_build_skills_state(runtime, session_id),
            }
        if approved_name == "skill" and runtime.skill_service is not None:
            runtime.skill_service.approve_skill(
                name=str(approved_args.get("name") or ""),
                session_id=session_id,
            )

        result_str = await execute(approved_name, approved_args)
        messages.append(ToolMessage(content=result_str, tool_call_id=approved_id))

        emit_event("status", {"delta": "Agent 已接收审批结果，继续执行..."})

        answer_text, next_approval = await _run_agent_loop(
            runtime,
            messages=messages,
            tools=all_tools,
            session_id=session_id,
            actor=actor,
            event_callback=persisted_event_callback,
        )

        if next_approval is not None:
            emit_event("status", {"delta": "Agent 需要新的人工确认。"})
            await _persist_pending_approval(
                runtime,
                conversation_id=resolved_conversation_id,
                session_id=session_id,
                workspace_id=workspace_id,
                approval_request=next_approval,
            )
            return {
                "status": "pending_approval",
                "conversation_id": resolved_conversation_id,
                "session_id": session_id,
                "workspace_id": workspace_id,
                "approval_request": next_approval,
                **_build_skills_state(runtime, session_id),
            }

        if not answer_text:
            answer_text = "当前没有生成有效回答。"
        answer_text = _summarize_tool_result_answer(
            approved_name,
            approved_args,
            result_str,
            answer_text,
        )
        await append_chat_message_dual_write(
            runtime,
            resolved_conversation_id,
            role="assistant",
            content=answer_text,
        )
        emit_event("status", {"delta": "Agent 已生成最终回答。"})
        return {
            "status": "completed",
            "conversation_id": resolved_conversation_id,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "answer": answer_text,
            **_build_skills_state(runtime, session_id),
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
            yield make_sse_event("skills", {
                "active_skills": result.get("active_skills") or [],
                "loaded_skills": result.get("loaded_skills") or [],
            })
            yield make_sse_event("done", {})
            return
        await clear_pending_approval_state(
            runtime,
            conversation_id=normalized_conversation_id,
            workspace_id=str(result.get("workspace_id") or "default"),
        )
        answer_text = str(result.get("answer") or "").strip()
        if answer_text:
            for chunk in _chunk_text(answer_text, chunk_size=48):
                yield make_sse_event("answer", {"delta": chunk})
        yield make_sse_event("skills", {
            "active_skills": result.get("active_skills") or [],
            "loaded_skills": result.get("loaded_skills") or [],
        })
        yield make_sse_event("done", {})
    except Exception as exc:
        yield make_sse_event(
            "error", {"detail": str(exc) or "Agent 恢复执行失败"}
        )
    finally:
        await _flush_persisted_event_tasks(persisted_event_tasks)


def _chunk_text(text: str, *, chunk_size: int = 64) -> list[str]:
    payload = str(text or "")
    if not payload:
        return []
    safe_chunk_size = max(int(chunk_size), 1)
    return [
        payload[index : index + safe_chunk_size]
        for index in range(0, len(payload), safe_chunk_size)
    ]


def _format_interrupt(runtime: Runtime, interrupt: Any) -> dict[str, Any]:
    """Legacy compat — used by unified_agent resume via import."""
    # Build from the interrupt value (kept for backward compat)
    value = interrupt.value if hasattr(interrupt, "value") else {}
    payload = value if isinstance(value, dict) else {}
    action_requests = []
    for item in list(payload.get("action_requests") or []):
        action = dict(item or {})
        tool_policy = (
            getattr(runtime.tool_service, "policy", None)
            if runtime.tool_service is not None
            else None
        )
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
