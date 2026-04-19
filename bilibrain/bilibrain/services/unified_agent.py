"""Unified ReAct Agent — merges QA retrieval and skill execution into one agent.

A single LLM with all tools (QA retrieval, workspace, skills). The agent
decides which tools to use via a ReAct loop — no intent classifier needed.

Implementation: llm.bind_tools() + while loop (no LangGraph agent,
no checkpointer, no msgpack serialization issues).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Callable

from langchain_core.messages import AIMessage, ToolMessage

from bilibrain.chat.assembler import assemble_unified_agent_context
from bilibrain.core.runtime import Runtime
from bilibrain.graphs.qa.events import make_sse_event
from bilibrain.graphs.qa.helpers import describe_query_scope
from bilibrain.services.chat_storage import (
    append_chat_message_dual_write,
    ensure_chat_store_session_loaded,
    replace_chat_message_dual_write,
)
from bilibrain.services.context_usage import get_conversation_context_usage
from bilibrain.services.chat_memory import (
    build_conversation_context,
    compact_conversation_context,
    refresh_context_stats_after_message,
    should_compact_context,
)
from bilibrain.services.common import estimate_text_tokens
from bilibrain.services.citations import normalize_answer_citations
from bilibrain.services.agent_runtime import (
    _consume_pending_approval,
    _format_interrupt,
    _persist_pending_approval,
    _summarize_tool_result_answer,
    get_default_workspace,
    get_or_create_conversation,
)
from bilibrain.services.runtime_events import (
    build_persisting_runtime_event_callback,
    clear_pending_approval_state,
)
from bilibrain.services.summary import resolve_query_scope
from bilibrain.services.workspace_context import select_workspace_context
from bilibrain.skills import build_skill_langchain_tools
from bilibrain.tools import build_langchain_tools
from bilibrain.tools.policy import evaluate_command_request
from bilibrain.tools.qa_tools import build_qa_retrieval_tools

logger = logging.getLogger(__name__)

# Tools that require HITL approval before execution
_HITL_TOOLS = {"run_command", "write_file", "append_file", "make_dir"}

# Max consecutive tool-call rounds to prevent infinite loops
_MAX_ROUNDS = 20


def _build_skills_state(runtime: Runtime, session_id: str) -> dict[str, Any]:
    if runtime.skill_service is None:
        return {"active_skills": [], "loaded_skills": []}
    return {
        "active_skills": runtime.skill_service.get_active_skills(session_id),
        "loaded_skills": runtime.skill_service.get_loaded_skills(session_id),
    }


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


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def build_unified_session_id(
    *, conversation_id: int | None = None, explicit_session_id: str | None = None
) -> str:
    explicit = str(explicit_session_id or "").strip()
    if explicit:
        return explicit
    if conversation_id:
        return f"conversation-{int(conversation_id)}"
    raise RuntimeError("session_id is required when conversation_id is not provided.")


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def build_unified_agent_prompt(
    runtime: Runtime,
    *,
    session_id: str,
    workspace_id: str,
    scope_description: str,
    memory_text: str,
    actor: str,
) -> str:
    # --- Skills ---
    available_skills = (
        runtime.skill_service.build_available_skills_prompt(session_id=session_id, actor=actor)
        if runtime.skill_service
        else "<available_skills />"
    )

    # --- Workspace tools ---
    tool_items = runtime.tool_service.list_tools() if runtime.tool_service else []
    tool_lines = []
    for item in tool_items:
        if not item.get("enabled", True):
            continue
        tool_lines.append(f"- {item['name']}: {item['description']}")
    tool_block = "\n".join(tool_lines) if tool_lines else "- 当前没有可用工具"

    # --- Memory ---
    memory_block = ""
    if memory_text:
        memory_block = f"\n## 对话记忆\n{memory_text}\n"

    return "\n".join(
        [
            "你是 BiliBrain 的统一 Agent，一个面向 B 站视频与收藏夹知识库的中文助手。",
            "你的首要目标是基于当前知识范围，为用户提供准确、克制、可执行的回答。",
            "",
            "## 答题决策流程",
            "每次收到用户请求，严格按以下顺序决策，不得跳步：",
            "",
            "### 第一步：匹配 Skill",
            "检查下方 <available_skills> 列表，根据每个 skill 的名称、描述、适用场景判断是否与用户意图匹配。",
            "- 若匹配：立即调用 skill(name) 读取完整 SKILL.md。",
            "- 读取后优先严格遵循该 skill 定义的流程、输出结构和资源使用方式。",
            "- 如果 skill 正文要求读取 references、scripts、assets 或其他文件，再继续调用普通工具按需处理。",
            "- skill 负责组织流程，不能替代事实来源。",
            "- 如果没有匹配的 skill，进入第二步。",
            "",
            "### 第二步：直接选工具",
            "如果没有匹配 skill，或 skill 明确要求调用工具，就根据下方工具规则选择合适工具，再基于真实返回内容回答。",
            "",
            "### 第三步：结果不足时",
            "- 若工具返回为空，或工具结果不能直接覆盖问题，明确告知用户“当前工具结果不足以支持这个结论”。",
            "- 不得用记忆、常识或推断补充知识库中没有的事实。",
            "",
            "## Skill 与工具的关系",
            "- Skill 负责组织流程、步骤顺序和输出结构。",
            "- 工具提供事实来源和执行结果。",
            "- 无论是否使用 skill，最终答案都必须有工具返回的真实内容作为支撑。",
            "",
            "## 工具使用规则",
            "### search_knowledge_base",
            "- 涉及具体视频内容、事实、步骤、定义、时间点等精确问题时调用。",
            "- 返回结果出来后再下结论，不得先写结论再补检索。",
            "",
            "### search_video_summaries",
            "- 涉及跨视频归纳、收藏夹整体概览、宏观总结、主题对比时调用。",
            "- 仅能基于工具真实返回做归纳，不得自行补充未返回的视频结论。",
            "",
            "### read_file / list_dir",
            "- 当 skill 正文要求读取 skill 附件、参考资料、脚本或当前 workspace 文件时调用。",
            "- 相对路径默认相对 skill(name) 返回的 BILIBRAIN_SKILL_DIR 或当前 workspace 解析。",
            "",
            "### write_file / append_file / make_dir",
            "- 仅在用户明确要求写文件、保存结果或创建目录时调用。",
            "- 用户没有明确要求落盘时，不要主动写文件。",
            "",
            "### run_command",
            "- 仅在确实需要执行本地命令或脚本时调用。",
            "- 拿到真实 stdout / stderr / error 后再继续，不得假设命令已成功。",
            "- 若命令失败，只有在返回内容明确给出依据时才能解释失败原因；否则只能如实说明当前结果没有提供具体原因。",
            "",
            "### web_search / browser_read_page",
            "- 仅在当前知识库工具不能覆盖、且任务确实需要外部网页信息时调用。",
            "- 拿到真实网页结果后再引用，不得把常识当网页结果。",
            "",
            "### skill(name)",
            "- 仅当 <available_skills> 中某个 skill 与当前任务明显匹配时调用。",
            "- <access> 为 allow 的 skill 可以直接调用；<access> 为 ask 的 skill 需要先审批。",
            "- skill(name) 会返回 BILIBRAIN_SKILL_DIR、resource_map、usage_rules；不得自动递归加载附件目录。",
            "",
            "## 引用规则",
            "- 使用 search_knowledge_base 或 search_video_summaries 的返回内容时，在正文中用 [N] 标注引用，N 对应 ref_index。",
            "- 只有明确由来源支撑的句子才加引用；过渡语和总结句不加。",
            "- 禁止使用“资料1”“来源1”“【1】”等其他格式。",
            "",
            "## 输出风格",
            "- 先结论，后依据。",
            "- 简洁，不冗长。",
            "- 全程中文。",
            "- 如果资料不足，直接说明，不要硬答。",
            "",
            f"## 当前范围\n{scope_description}",
            "",
            f"当前 workspace_id: {workspace_id}",
            "",
            "## 当前可用工具",
            tool_block,
            "",
            "## 当前可用 skills 摘要",
            available_skills,
            memory_block,
        ]
    )


async def _estimate_compaction_overhead_tokens(
    runtime: Runtime,
    *,
    session_id: str,
    workspace_id: str,
    scope_description: str,
    query: str,
    actor: str,
) -> int:
    prompt_without_memory = build_unified_agent_prompt(
        runtime,
        session_id=session_id,
        workspace_id=workspace_id,
        scope_description=scope_description,
        memory_text="",
        actor=actor,
    )
    workspace_context = await select_workspace_context(runtime, query=query)
    return (
        estimate_text_tokens(prompt_without_memory)
        + workspace_context.token_estimate
        + estimate_text_tokens(str(query or "").strip())
    )


# ---------------------------------------------------------------------------
# Tool executor — handles HITL approval inline
# ---------------------------------------------------------------------------

def _build_tool_executor(
    tools: list[Any],
    *,
    runtime: Runtime,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
):
    """Build a name→callable lookup for tool execution."""
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
            logger.exception("Tool %s execution failed", name)
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
    """Build an approval request payload for a HITL tool call."""
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
# Core agent loop: bind_tools + while loop
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
    """Run the ReAct loop. Returns (answer_text, approval_request_or_None).

    If an approval_request is returned, the caller should yield it to the
    client and wait for a resume decision.
    """
    llm = runtime.qwen.model.bind_tools(tools)
    tool_map, execute = _build_tool_executor(
        tools, runtime=runtime, event_callback=event_callback,
    )

    for _round in range(_MAX_ROUNDS):
        # Call LLM
        if event_callback is not None:
            event_callback("status", {"delta": "正在思考并决定下一步..."})

        response = await llm.ainvoke(messages)

        # If no tool calls, we're done — extract text answer
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

        # Append the AI message with tool calls to history
        messages.append(response)

        # Process each tool call
        for tc in tool_calls:
            tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")

            # ── HITL check ─────────────────────────────────────────────
            if tc_name in _HITL_TOOLS:
                approval_request = _build_approval_request(
                    runtime, tc_name, tc_args, tc_id,
                )
                # Return immediately — caller must handle approval
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
                        event_callback("skill", {
                            "phase": "approval_required",
                            "name": skill_name,
                            "session_id": session_id,
                            "error": decision.reason,
                        })
                    approval_request = _build_skill_approval_request(
                        runtime,
                        skill_name=skill_name,
                        call_id=tc_id,
                        session_id=session_id,
                        actor=actor,
                    )
                    return "", approval_request

            # ── Execute tool ────────────────────────────────────────────
            result_str = await execute(tc_name, tc_args)

            messages.append(ToolMessage(content=result_str, tool_call_id=tc_id))

    return "已达最大推理轮次，请精简问题后重试。", None


async def _stream_agent_loop(
    runtime: Runtime,
    *,
    messages: list[Any],
    tools: list[Any],
    session_id: str,
    actor: str,
    emit_event: Callable[[str, dict[str, Any] | None], None],
) -> tuple[str, dict[str, Any] | None]:
    """Streaming version of the ReAct loop.

    Tokens from the final LLM answer are emitted as ``answer_token`` events
    via *emit_event*. Tool execution events are also emitted.
    """
    llm = runtime.qwen.model.bind_tools(tools)
    tool_map, execute = _build_tool_executor(
        tools, runtime=runtime, event_callback=emit_event,
    )

    for _round in range(_MAX_ROUNDS):
        emit_event("status", {"delta": "正在思考并决定下一步..."})

        # Stream the LLM response
        collected_chunks: list[Any] = []
        tool_call_chunks_acc: list[dict[str, Any]] = []
        full_text = ""

        chunk_count = 0
        async for chunk in llm.astream(messages):
            collected_chunks.append(chunk)
            chunk_count += 1

            # Check for tool_call_chunks on this chunk
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

                # Accumulate by index
                while len(tool_call_chunks_acc) <= idx:
                    tool_call_chunks_acc.append({"name": "", "args": "", "id": ""})
                entry = tool_call_chunks_acc[idx]
                if name:
                    entry["name"] = name
                if args_str:
                    entry["args"] += args_str
                if tc_id:
                    entry["id"] = tc_id

            # Emit reasoning tokens (qwen3.5 thinking content)
            msg = getattr(chunk, "message", chunk)
            reasoning = (
                getattr(msg, "additional_kwargs", {}).get("reasoning_content")
                if hasattr(msg, "additional_kwargs")
                else None
            )
            if isinstance(reasoning, str) and reasoning:
                emit_event("reasoning", {"delta": reasoning})

            # Emit text tokens only when there are no tool_call_chunks
            content = getattr(chunk, "content", None)
            if isinstance(content, str) and content and not tc_chunks:
                full_text += content
                emit_event("answer_token", {"delta": content})

        # If there were tool call chunks, assemble them
        has_tool_calls = bool(tool_call_chunks_acc) and any(
            e.get("name") for e in tool_call_chunks_acc
        )

        if not has_tool_calls:
            # Final answer — no more tool calls
            return full_text.strip(), None

        # Reconstruct tool_calls from accumulated chunks
        tool_calls: list[dict[str, Any]] = []
        for entry in tool_call_chunks_acc:
            if not entry.get("name"):
                continue
            args_raw = entry.get("args", "")
            try:
                args = json.loads(args_raw) if args_raw else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({
                "name": entry["name"],
                "args": args,
                "id": entry.get("id", ""),
            })

        # Build a synthetic AIMessage with tool_calls and append
        ai_msg = AIMessage(
            content=full_text,
            tool_calls=tool_calls,
        )
        messages.append(ai_msg)

        # Process each tool call
        for tc in tool_calls:
            tc_name = tc["name"]
            tc_args = tc["args"]
            tc_id = tc["id"]

            # ── HITL check ─────────────────────────────────────────────
            if tc_name in _HITL_TOOLS:
                approval_request = _build_approval_request(
                    runtime, tc_name, tc_args, tc_id,
                )
                return full_text.strip(), approval_request

            if tc_name == "skill":
                skill_name = str((tc_args or {}).get("name") or "").strip()
                decision = runtime.skill_service.evaluate_skill_access(
                    name=skill_name,
                    session_id=session_id,
                    actor=actor,
                ) if runtime.skill_service is not None else None
                if decision is not None and decision.requires_approval:
                    emit_event("skill", {
                        "phase": "approval_required",
                        "name": skill_name,
                        "session_id": session_id,
                        "error": decision.reason,
                    })
                    approval_request = _build_skill_approval_request(
                        runtime,
                        skill_name=skill_name,
                        call_id=tc_id,
                        session_id=session_id,
                        actor=actor,
                    )
                    return full_text.strip(), approval_request

            # ── Execute tool ────────────────────────────────────────────
            result_str = await execute(tc_name, tc_args)

            messages.append(ToolMessage(content=result_str, tool_call_id=tc_id))

    return "已达最大推理轮次，请精简问题后重试。", None


def _summarize_tool_args(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Lightweight summary of tool args for SSE events."""
    if tool_name == "run_command":
        return {"command": str(arguments.get("command") or ""), "cwd": str(arguments.get("cwd") or ".")}
    if tool_name == "web_search":
        return {"query": str(arguments.get("query") or "")}
    if tool_name in {"write_file", "append_file"}:
        content = str(arguments.get("content") or "")
        return {"path": str(arguments.get("path") or ""), "content_length": len(content)}
    if tool_name == "make_dir":
        return {"path": str(arguments.get("path") or "")}
    return {"path": str(arguments.get("path") or ".")} if tool_name in {"read_file", "list_dir"} else {}


# ---------------------------------------------------------------------------
# Answer extraction (kept for compatibility)
# ---------------------------------------------------------------------------

def _extract_text_from_content(content: Any) -> str:
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


# ---------------------------------------------------------------------------
# Pre-processing
# ---------------------------------------------------------------------------

async def _preprocess(
    runtime: Runtime,
    *,
    query: str,
    folder_id: int | None,
    bvid: str | None,
    scope_mode: str | None,
    conversation_id: int | None,
    actor: str,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Resolve scope, load context, compact memory, persist user message."""
    # 1. Ensure conversation
    conversation = await get_or_create_conversation(runtime, conversation_id)
    resolved_conversation_id = int(conversation["conversation_id"])
    await ensure_chat_store_session_loaded(runtime, resolved_conversation_id)

    # 2. Resolve scope
    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    scope_description = await describe_query_scope(
        runtime,
        folder_id=scope["folder_id"] if scope["scope"] == "folder" else folder_id,
        bvid=scope["bvid"] if scope["scope"] == "video" else bvid,
        scope_mode=scope_mode,
    )
    session_id = build_unified_session_id(conversation_id=resolved_conversation_id)
    workspace_id = "default"
    if runtime.tool_service is not None:
        workspace = await get_default_workspace(runtime, actor=actor)
        workspace_id = str(workspace.get("workspace_id") or "default").strip() or "default"

    # 3. Load conversation context
    context = await build_conversation_context(
        runtime, conversation_id=resolved_conversation_id,
    )
    extra_token_budget = await _estimate_compaction_overhead_tokens(
        runtime,
        session_id=session_id,
        workspace_id=workspace_id,
        scope_description=scope_description,
        query=query,
        actor=actor,
    )

    # 4. Compact if needed
    if should_compact_context(runtime, context, extra_token_budget=extra_token_budget):
        context = await compact_conversation_context(
            runtime, conversation_id=resolved_conversation_id, context=context,
        )

    memory_text = context.memory_text

    # 5. Persist user message
    user_message = await append_chat_message_dual_write(
        runtime,
        resolved_conversation_id, role="user", content=query,
    )
    await refresh_context_stats_after_message(
        runtime, conversation_id=resolved_conversation_id, message=user_message,
    )

    return {
        "conversation_id": resolved_conversation_id,
        "scope": scope,
        "scope_description": scope_description,
        "memory_text": memory_text,
    }


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

async def _postprocess(
    runtime: Runtime,
    *,
    answer_text: str,
    sources: list[dict[str, str]],
    conversation_id: int,
    route_mode: str | None = None,
    placeholder_message_id: int | None = None,
) -> dict[str, Any]:
    """Normalize citations and persist assistant message."""
    normalized = normalize_answer_citations(answer_text)

    answer_mode = "chunk"
    if sources:
        first_source = sources[0]
        answer_mode = (
            "summary" if first_source.get("source_kind") == "summary" else "chunk"
        )

    if placeholder_message_id is not None:
        assistant_message = await replace_chat_message_dual_write(
            runtime,
            conversation_id=conversation_id,
            message_id=placeholder_message_id,
            content=normalized,
            sources=sources,
            answer_mode=answer_mode,
            route_mode=route_mode,
        )
    else:
        assistant_message = await append_chat_message_dual_write(
            runtime,
            conversation_id,
            "assistant",
            normalized,
            sources=sources,
            answer_mode=answer_mode,
            route_mode=route_mode,
        )
    await refresh_context_stats_after_message(
        runtime, conversation_id=conversation_id, message=assistant_message,
    )

    return {
        "assistant_message": assistant_message,
        "answer_text": normalized,
        "answer_mode": answer_mode,
    }


# ---------------------------------------------------------------------------
# Shared helper: build tools + messages for a conversation turn
# ---------------------------------------------------------------------------

async def _build_turn_context(
    runtime: Runtime,
    *,
    ctx: dict[str, Any],
    query: str,
    folder_id: int | None,
    bvid: str | None,
    session_id: str,
    workspace_id: str,
    approval_mode=None,
    actor: str = "agent",
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    collected_sources: list[dict[str, str]] | None = None,
) -> tuple[Any, list[Any]]:
    """Build assembled context + tools for one agent turn."""

    if collected_sources is None:
        collected_sources = []

    def qa_event_callback(event_type: str, data: dict[str, Any]) -> None:
        if event_type == "sources" and data.get("sources"):
            collected_sources.extend(data["sources"])
        if event_callback is not None:
            event_callback(event_type, data)

    # Build tools
    qa_tools = build_qa_retrieval_tools(
        runtime, folder_id=folder_id, bvid=bvid, event_callback=qa_event_callback,
    )
    skill_tools = build_skill_langchain_tools(
        runtime.skill_service, session_id=session_id, actor=actor,
        event_callback=event_callback,
    )
    workspace_tools = build_langchain_tools(
        runtime.tool_service, workspace_id=workspace_id, actor=actor,
        approval_mode=approval_mode, event_callback=event_callback,
    )
    all_tools = [*qa_tools, *skill_tools, *workspace_tools]

    assembled = await assemble_unified_agent_context(
        runtime,
        conversation_id=int(ctx["conversation_id"]),
        query=query,
        system_prompt_builder=lambda memory_text: build_unified_agent_prompt(
            runtime,
            session_id=session_id,
            workspace_id=workspace_id,
            scope_description=ctx["scope_description"],
            memory_text=memory_text,
            actor=actor,
        ),
    )
    return assembled, all_tools


async def _emit_context_usage(
    runtime: Runtime,
    *,
    conversation_id: int,
    emit: Callable[[str, dict[str, Any] | None], None] | None,
) -> None:
    if emit is None:
        return
    usage = await get_conversation_context_usage(runtime, conversation_id)
    emit("context", usage)


# ---------------------------------------------------------------------------
# Non-streaming entry
# ---------------------------------------------------------------------------

async def answer_with_unified_agent(
    runtime: Runtime,
    *,
    query: str,
    folder_id: int | None = None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
    session_id: str | None = None,
    approval_mode=None,
    actor: str = "agent",
) -> dict[str, Any]:
    return await _execute_unified_agent_turn(
        runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        conversation_id=conversation_id,
        session_id=session_id,
        approval_mode=approval_mode,
        actor=actor,
        event_callback=None,
    )


async def _execute_unified_agent_turn(
    runtime: Runtime,
    *,
    query: str,
    folder_id: int | None,
    bvid: str | None,
    scope_mode: str | None,
    conversation_id: int | None,
    session_id: str | None,
    approval_mode,
    actor: str,
    event_callback: Callable[[str, dict[str, Any]], None] | None,
) -> dict[str, Any]:
    """Run one turn of the unified agent: preprocess → loop → postprocess."""
    persisted_event_tasks: list[asyncio.Task[None]] = []
    # --- Pre-processing ---
    if event_callback is not None:
        event_callback("status", {"delta": "正在准备会话上下文..."})

    try:
        ctx = await _preprocess(
            runtime,
            query=query,
            folder_id=folder_id,
            bvid=bvid,
            scope_mode=scope_mode,
            conversation_id=conversation_id,
            actor=actor,
            event_callback=event_callback,
        )
        resolved_conversation_id = ctx["conversation_id"]
        resolved_session_id = build_unified_session_id(
            conversation_id=resolved_conversation_id,
            explicit_session_id=session_id,
        )
        workspace = await get_default_workspace(runtime, actor=actor)
        workspace_id = workspace["workspace_id"]
        persisted_event_callback = _build_persisting_event_callback(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=workspace_id,
            downstream=event_callback,
            tasks=persisted_event_tasks,
        )

        if event_callback is not None:
            event_callback("status", {"delta": "正在加载工具与技能..."})

        collected_sources: list[dict[str, str]] = []
        assembled, all_tools = await _build_turn_context(
            runtime,
            ctx=ctx,
            query=query,
            folder_id=folder_id,
            bvid=bvid,
            session_id=resolved_session_id,
            workspace_id=workspace_id,
            approval_mode=approval_mode,
            actor=actor,
            event_callback=persisted_event_callback,
            collected_sources=collected_sources,
        )
        messages = assembled.messages

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
                workspace_id=workspace_id,
                approval_request=approval_request,
            )
            if event_callback is not None:
                event_callback("status", {"delta": "需要人工确认后才能继续。"})
            return {
                "status": "pending_approval",
                "conversation_id": resolved_conversation_id,
                "session_id": resolved_session_id,
                "workspace_id": workspace_id,
                "approval_request": approval_request,
                "_pending_messages": messages,
                "_pending_tools": all_tools,
                "_pending_sources": collected_sources,
                **_build_skills_state(runtime, resolved_session_id),
            }

        await clear_pending_approval_state(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=str(workspace_id or "default"),
        )
        if not answer_text:
            answer_text = "当前没有生成有效回答。"

        if event_callback is not None:
            event_callback("status", {"delta": "正在保存回答..."})

        post = await _postprocess(
            runtime,
            answer_text=answer_text,
            sources=collected_sources,
            conversation_id=resolved_conversation_id,
            route_mode="kb_qa" if collected_sources else "direct",
        )
        await _emit_context_usage(
            runtime,
            conversation_id=resolved_conversation_id,
            emit=event_callback,
        )

        return {
            "status": "completed",
            "conversation_id": resolved_conversation_id,
            "session_id": resolved_session_id,
            "workspace_id": workspace_id,
            "answer": post["answer_text"],
            "answer_mode": post["answer_mode"],
            "assistant_message": post["assistant_message"],
            "sources": collected_sources,
            **_build_skills_state(runtime, resolved_session_id),
        }
    finally:
        await _flush_persisted_event_tasks(persisted_event_tasks)


# ---------------------------------------------------------------------------
# Streaming entry
# ---------------------------------------------------------------------------

async def stream_unified_agent_events(
    runtime: Runtime,
    *,
    query: str,
    folder_id: int | None = None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    conversation_id: int | None = None,
    session_id: str | None = None,
    approval_mode=None,
    actor: str = "agent",
) -> AsyncIterator[str]:
    """SSE streaming with real token-by-token output via astream()."""
    persisted_event_tasks: list[asyncio.Task[None]] = []
    # ── Resolve conversation ──────────────────────────────────────────────
    conversation = await get_or_create_conversation(runtime, conversation_id)
    resolved_conversation_id = int(conversation["conversation_id"])
    resolved_session_id = build_unified_session_id(
        conversation_id=resolved_conversation_id,
        explicit_session_id=session_id,
    )

    yield make_sse_event("conversation", {"conversation_id": resolved_conversation_id})
    yield make_sse_event("status", {"delta": "Agent 正在准备..."})

    if getattr(runtime, "skill_service", None) is not None:
        yield make_sse_event(
            "skills",
            _build_skills_state(runtime, resolved_session_id),
        )

    # ── Pre-processing ────────────────────────────────────────────────────
    queue: asyncio.Queue[tuple[str, dict[str, Any] | None] | None] = asyncio.Queue()

    def emit_event(event_type: str, data: dict[str, Any] | None = None) -> None:
        queue.put_nowait((event_type, data or {}))

    try:
        emit_event("status", {"delta": "正在准备会话上下文..."})

        ctx = await _preprocess(
            runtime,
            query=query,
            folder_id=folder_id,
            bvid=bvid,
            scope_mode=scope_mode,
            conversation_id=resolved_conversation_id,
            actor=actor,
        )

        # ── Build workspace ───────────────────────────────────────────────
        workspace = await get_default_workspace(runtime, actor=actor)
        workspace_id = workspace["workspace_id"]
        persisted_event_callback = _build_persisting_event_callback(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=workspace_id,
            downstream=emit_event,
            tasks=persisted_event_tasks,
        )

        emit_event("status", {"delta": "正在加载工具与技能..."})

        # ── Build tools + messages ────────────────────────────────────────
        collected_sources: list[dict[str, str]] = []

        assembled, all_tools = await _build_turn_context(
            runtime,
            ctx=ctx,
            query=query,
            folder_id=folder_id,
            bvid=bvid,
            session_id=resolved_session_id,
            workspace_id=workspace_id,
            approval_mode=approval_mode,
            actor=actor,
            event_callback=persisted_event_callback,
            collected_sources=collected_sources,
        )
        messages = assembled.messages

        # ── Run streaming agent loop in background ────────────────────────
        full_answer = ""
        approval_request: dict[str, Any] | None = None

        async def run_loop() -> None:
            nonlocal full_answer, approval_request
            try:
                full_answer, approval_request = await _stream_agent_loop(
                    runtime,
                    messages=messages,
                    tools=all_tools,
                    session_id=resolved_session_id,
                    actor=actor,
                    emit_event=persisted_event_callback,
                )
            except Exception as exc:
                logger.exception("Agent loop failed")
                emit_event("error", {"detail": str(exc) or "Agent 执行失败"})

        # ── Forward events from queue ─────────────────────────────────────
        task = asyncio.create_task(run_loop())
        answer_started = False

        while True:
            if task.done() and queue.empty():
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.1)
            except TimeoutError:
                continue
            if item is None:
                continue
            ev_type, data = item

            if ev_type == "answer_token":
                delta = (data or {}).get("delta", "")
                if delta:
                    yield make_sse_event("answer", {"delta": delta})
                    answer_started = True
            elif ev_type == "error":
                yield make_sse_event("error", data or {})
                return
            else:
                yield make_sse_event(ev_type, data or {})

        await task  # propagate any uncaught exception

        # ── HITL interrupt path ───────────────────────────────────────────
        if approval_request is not None:
            await _persist_pending_approval(
                runtime,
                conversation_id=resolved_conversation_id,
                session_id=resolved_session_id,
                workspace_id=workspace_id,
                approval_request=approval_request,
            )
            yield make_sse_event("approval", {
                "session_id": resolved_session_id,
                "workspace_id": workspace_id,
                "approval_request": approval_request,
            })
            yield make_sse_event("skills", _build_skills_state(runtime, resolved_session_id))
            yield make_sse_event("done", {})
            return

        # ── Post-processing ───────────────────────────────────────────────
        await clear_pending_approval_state(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=str(workspace_id or "default"),
        )
        if full_answer:
            normalized = normalize_answer_citations(full_answer)
            yield make_sse_event("answer_normalized", {"text": normalized})

            answer_mode = "chunk"
            if collected_sources:
                first_source = collected_sources[0]
                answer_mode = "summary" if first_source.get("source_kind") == "summary" else "chunk"

            route_mode = "kb_qa" if collected_sources else "direct"

            await _postprocess(
                runtime,
                answer_text=normalized,
                sources=collected_sources,
                conversation_id=resolved_conversation_id,
                route_mode=route_mode,
            )
            yield make_sse_event(
                "context",
                await get_conversation_context_usage(runtime, resolved_conversation_id),
            )

            if collected_sources:
                yield make_sse_event("sources", {"sources": collected_sources})
            yield make_sse_event("mode", {"mode": answer_mode})
            yield make_sse_event("route", {"route_mode": route_mode})
        else:
            yield make_sse_event("route", {"route_mode": "direct"})

        yield make_sse_event("skills", _build_skills_state(runtime, resolved_session_id))
        yield make_sse_event("done", {})

    except Exception as exc:
        logger.exception("Unified agent streaming failed")
        try:
            _full = locals().get("full_answer", "")
            _sources = locals().get("collected_sources") or []
            if _full:
                await _postprocess(
                    runtime,
                    answer_text=_full,
                    sources=_sources,
                    conversation_id=resolved_conversation_id,
                    route_mode="direct",
                )
        except Exception:
            pass
        yield make_sse_event("error", {"detail": str(exc) or "Agent 执行失败"})
    finally:
        await _flush_persisted_event_tasks(persisted_event_tasks)


# ---------------------------------------------------------------------------
# Resume (HITL) — rebuilds context and continues the while loop
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


async def resume_unified_agent_turn(
    runtime: Runtime,
    *,
    session_id: str,
    decision: dict[str, Any],
    conversation_id: int | None = None,
    folder_id: int | None = None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    actor: str = "agent",
) -> dict[str, Any]:
    """Resume after HITL approval — re-run the loop with the approved tool call injected."""
    persisted_event_tasks: list[asyncio.Task[None]] = []
    resolved_conversation_id = _resolve_conversation_id(session_id, conversation_id)

    try:
        conversation = await get_or_create_conversation(runtime, resolved_conversation_id)
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
            downstream=None,
            tasks=persisted_event_tasks,
        )

        scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
        scope_description = await describe_query_scope(
            runtime,
            folder_id=scope["folder_id"] if scope["scope"] == "folder" else folder_id,
            bvid=scope["bvid"] if scope["scope"] == "video" else bvid,
            scope_mode=scope_mode,
        )

        collected_sources: list[dict[str, str]] = []

        def qa_cb(event_type: str, data: dict[str, Any]) -> None:
            if event_type == "sources" and data.get("sources"):
                collected_sources.extend(data["sources"])
            persisted_event_callback(event_type, data)

        qa_tools = build_qa_retrieval_tools(
            runtime, folder_id=folder_id, bvid=bvid, event_callback=qa_cb,
        )
        skill_tools = build_skill_langchain_tools(
            runtime.skill_service, session_id=session_id, actor=actor,
            event_callback=persisted_event_callback,
        )
        workspace_tools = build_langchain_tools(
            runtime.tool_service, workspace_id=workspace_id, actor=actor,
            event_callback=persisted_event_callback,
        )
        all_tools = [*qa_tools, *skill_tools, *workspace_tools]
        _, execute = _build_tool_executor(
            all_tools, runtime=runtime, event_callback=persisted_event_callback,
        )

        assembled = await assemble_unified_agent_context(
            runtime,
            conversation_id=resolved_conversation_id,
            query="",
            system_prompt_builder=lambda _memory_text: build_unified_agent_prompt(
                runtime,
                session_id=session_id,
                workspace_id=workspace_id,
                scope_description=scope_description,
                memory_text="",
                actor=actor,
            ),
        )
        messages = list(assembled.messages)

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
                resolved_conversation_id, role="assistant", content=answer_text,
            )
            await refresh_context_stats_after_message(
                runtime, conversation_id=resolved_conversation_id, message=assistant_message,
            )
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

        answer_text = normalize_answer_citations(
            _summarize_tool_result_answer(
                approved_name,
                approved_args,
                result_str,
                answer_text,
            )
        )
        assistant_message = await append_chat_message_dual_write(
            runtime,
            resolved_conversation_id, role="assistant", content=answer_text,
        )
        await refresh_context_stats_after_message(
            runtime, conversation_id=resolved_conversation_id, message=assistant_message,
        )

        return {
            "status": "completed",
            "conversation_id": resolved_conversation_id,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "answer": answer_text,
            **_build_skills_state(runtime, session_id),
        }
    finally:
        await _flush_persisted_event_tasks(persisted_event_tasks)


async def stream_resume_unified_agent_events(
    runtime: Runtime,
    *,
    session_id: str,
    decision: dict[str, Any],
    conversation_id: int | None = None,
    folder_id: int | None = None,
    bvid: str | None = None,
    scope_mode: str | None = None,
    actor: str = "agent",
) -> AsyncIterator[str]:
    """SSE streaming for agent resume — real token-by-token."""
    persisted_event_tasks: list[asyncio.Task[None]] = []
    normalized_conversation_id = _resolve_conversation_id(session_id, conversation_id)

    yield make_sse_event("conversation", {"conversation_id": normalized_conversation_id})
    yield make_sse_event("status", {"delta": "Agent 正在恢复执行..."})

    if runtime.skill_service is not None:
        yield make_sse_event(
            "skills",
            _build_skills_state(runtime, session_id),
        )

    queue: asyncio.Queue[tuple[str, dict[str, Any] | None] | None] = asyncio.Queue()

    def emit_event(event_type: str, data: dict[str, Any] | None = None) -> None:
        queue.put_nowait((event_type, data or {}))

    emit_event("status", {"delta": "已接收审批结果，继续执行..."})

    # Rebuild context
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

    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    scope_description = await describe_query_scope(
        runtime,
        folder_id=scope["folder_id"] if scope["scope"] == "folder" else folder_id,
        bvid=scope["bvid"] if scope["scope"] == "video" else bvid,
        scope_mode=scope_mode,
    )

    collected_sources: list[dict[str, str]] = []

    def qa_cb(et: str, d: dict[str, Any]) -> None:
        if et == "sources" and d.get("sources"):
            collected_sources.extend(d["sources"])
        persisted_event_callback(et, d)

    qa_tools = build_qa_retrieval_tools(runtime, folder_id=folder_id, bvid=bvid, event_callback=qa_cb)
    skill_tools = build_skill_langchain_tools(
        runtime.skill_service, session_id=session_id, actor=actor, event_callback=persisted_event_callback,
    )
    workspace_tools = build_langchain_tools(
        runtime.tool_service, workspace_id=workspace_id, actor=actor, event_callback=persisted_event_callback,
    )
    all_tools = [*qa_tools, *skill_tools, *workspace_tools]
    _, execute = _build_tool_executor(
        all_tools, runtime=runtime, event_callback=persisted_event_callback,
    )

    assembled = await assemble_unified_agent_context(
        runtime,
        conversation_id=resolved_conversation_id,
        query="",
        system_prompt_builder=lambda _memory_text: build_unified_agent_prompt(
            runtime,
            session_id=session_id,
            workspace_id=workspace_id,
            scope_description=scope_description,
            memory_text="",
            actor=actor,
        ),
    )
    messages = list(assembled.messages)

    # Inject approved tool call
    approved_name = str(action.get("name") or "")
    approved_args = effective_args
    approved_id = str(action.get("id") or f"resume-{approved_name}")

    messages.append(AIMessage(
        content="",
        tool_calls=[{"name": approved_name, "args": approved_args, "id": approved_id}],
    ))

    if decision_type == "reject":
        full_answer = str(decision.get("message") or "用户拒绝了当前操作。").strip()
        assistant_message = await append_chat_message_dual_write(
            runtime,
            resolved_conversation_id, role="assistant", content=full_answer,
        )
        await refresh_context_stats_after_message(
            runtime, conversation_id=resolved_conversation_id, message=assistant_message,
        )
        emit_event("status", {"delta": "用户拒绝了当前操作。"})
        yield make_sse_event("answer", {"delta": full_answer})
        yield make_sse_event(
            "context",
            await get_conversation_context_usage(runtime, resolved_conversation_id),
        )
        yield make_sse_event("skills", _build_skills_state(runtime, session_id))
        yield make_sse_event("done", {})
        return
    if approved_name == "skill" and runtime.skill_service is not None:
        runtime.skill_service.approve_skill(
            name=str(approved_args.get("name") or ""),
            session_id=session_id,
        )

    result_str = await execute(approved_name, approved_args)
    messages.append(ToolMessage(content=result_str, tool_call_id=approved_id))

    # ── Run streaming agent loop in background ────────────────────────────
    full_answer = ""
    next_approval: dict[str, Any] | None = None

    async def run_loop() -> None:
        nonlocal full_answer, next_approval
        try:
                full_answer, next_approval = await _stream_agent_loop(
                    runtime,
                    messages=messages,
                    tools=all_tools,
                    session_id=session_id,
                    actor=actor,
                    emit_event=persisted_event_callback,
                )
        except Exception as exc:
            logger.exception("Agent resume loop failed")
            emit_event("error", {"detail": str(exc) or "Agent 恢复执行失败"})

    # ── Forward events from queue ─────────────────────────────────────────
    try:
        task = asyncio.create_task(run_loop())

        while True:
            if task.done() and queue.empty():
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.1)
            except TimeoutError:
                continue
            if item is None:
                continue
            ev_type, data = item

            if ev_type == "answer_token":
                delta = (data or {}).get("delta", "")
                if delta:
                    yield make_sse_event("answer", {"delta": delta})
            elif ev_type == "error":
                yield make_sse_event("error", data or {})
                return
            else:
                yield make_sse_event(ev_type, data or {})

        await task

        # ── HITL interrupt ────────────────────────────────────────────────
        if next_approval is not None:
            await _persist_pending_approval(
                runtime,
                conversation_id=resolved_conversation_id,
                session_id=session_id,
                workspace_id=workspace_id,
                approval_request=next_approval,
            )
            yield make_sse_event("approval", {
                "session_id": session_id,
                "workspace_id": workspace_id,
                "approval_request": next_approval,
            })
            yield make_sse_event("skills", _build_skills_state(runtime, session_id))
            yield make_sse_event("done", {})
            return

        # ── Persist & finalize ────────────────────────────────────────────
        if not full_answer:
            full_answer = "当前没有生成有效回答。"

        normalized = normalize_answer_citations(
            _summarize_tool_result_answer(
                approved_name,
                approved_args,
                result_str,
                full_answer,
            )
        )
        assistant_message = await append_chat_message_dual_write(
            runtime,
            resolved_conversation_id, role="assistant", content=normalized,
        )
        await refresh_context_stats_after_message(
            runtime, conversation_id=resolved_conversation_id, message=assistant_message,
        )
        await clear_pending_approval_state(
            runtime,
            conversation_id=resolved_conversation_id,
            workspace_id=str(workspace_id or "default"),
        )

        yield make_sse_event(
            "context",
            await get_conversation_context_usage(runtime, resolved_conversation_id),
        )
        yield make_sse_event("skills", _build_skills_state(runtime, session_id))
        yield make_sse_event("done", {})

    except Exception as exc:
        logger.exception("Unified agent resume streaming failed")
        if full_answer:
            try:
                await append_chat_message_dual_write(
                    runtime,
                    resolved_conversation_id, role="assistant", content=full_answer,
                )
            except Exception:
                pass
        yield make_sse_event("error", {"detail": str(exc) or "Agent 恢复执行失败"})
    finally:
        await _flush_persisted_event_tasks(persisted_event_tasks)
