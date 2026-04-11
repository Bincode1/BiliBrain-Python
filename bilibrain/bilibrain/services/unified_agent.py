"""Unified ReAct Agent — merges QA retrieval and Skill Agent into one agent.

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

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from bilibrain.core.runtime import Runtime
from bilibrain.graphs.qa.events import make_sse_event
from bilibrain.graphs.qa.helpers import describe_query_scope
from bilibrain.services.chat_memory import (
    build_conversation_context,
    compact_conversation_context,
    refresh_context_stats_after_message,
    should_compact_context,
)
from bilibrain.services.citations import normalize_answer_citations
from bilibrain.services.skill_agent import (
    _format_interrupt,
    build_skill_agent_history,
    ensure_skill_agent_conversation,
    ensure_skill_agent_workspace,
)
from bilibrain.services.summary import resolve_query_scope
from bilibrain.skills import build_skill_langchain_tools
from bilibrain.tools import build_langchain_tools
from bilibrain.tools.policy import evaluate_command_request
from bilibrain.tools.qa_tools import build_qa_retrieval_tools

logger = logging.getLogger(__name__)

# Tools that require HITL approval before execution
_HITL_TOOLS = {"run_command", "write_file", "append_file", "make_dir"}

# Max consecutive tool-call rounds to prevent infinite loops
_MAX_ROUNDS = 20


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
) -> str:
    # --- Skills ---
    available_skills = (
        runtime.skill_service.build_available_skills_prompt(session_id=session_id)
        if runtime.skill_service
        else "<available_skills />"
    )
    active_skills = (
        runtime.skill_service.build_active_skills_prompt(session_id=session_id)
        if runtime.skill_service
        else "<active_skills />"
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
            "你是 BiliBrain，一个 Bilibili 视频知识助手。",
            "",
            "## 核心规则",
            "1. 只使用检索到的资料回答知识问题，不要补充外部知识",
            "2. 关键结论附上资料编号，格式【n】",
            "3. 只能使用资料里已有的编号",
            "4. 如果资料不足，直接说明",
            "",
            "## 工具使用策略",
            "- search_knowledge_base：查具体细节、事实、步骤、定义、时间点",
            "- search_video_summaries：做总结、概括、归纳、对比、梳理整体观点",
            "- read_file / write_file / list_dir / ...：文件操作（限 workspace 内）",
            "- run_command：执行命令",
            "- web_search / browser_read_page：网络搜索和网页读取",
            "",
            "## 技能使用",
            "- <active_skills> 包含用户已激活的技能指令，根据问题自动判断是否需要遵循",
            "- 如果问题匹配某个已激活技能的场景，按其指引执行",
            "- 如果没有匹配的激活技能，用通用能力回答",
            "",
            "## 文件与命令",
            "- 对文件和命令操作保持克制，只在当前 workspace 内工作",
            "- 如果工具由于审批策略失败，要明确告诉用户需要预批准，而不是伪造执行结果",
            "",
            f"## 当前范围\n{scope_description}",
            "",
            f"当前 workspace_id: {workspace_id}",
            "",
            "## 当前可用工具",
            tool_block,
            "",
            "## 当前技能目录",
            available_skills,
            "",
            "## 当前已激活 skills",
            active_skills,
            memory_block,
        ]
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


# ---------------------------------------------------------------------------
# Core agent loop: bind_tools + while loop
# ---------------------------------------------------------------------------

async def _run_agent_loop(
    runtime: Runtime,
    *,
    messages: list[Any],
    tools: list[Any],
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

            # ── Execute tool ────────────────────────────────────────────
            result_str = await execute(tc_name, tc_args)

            messages.append(ToolMessage(content=result_str, tool_call_id=tc_id))

    return "已达最大推理轮次，请精简问题后重试。", None


async def _stream_agent_loop(
    runtime: Runtime,
    *,
    messages: list[Any],
    tools: list[Any],
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
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Resolve scope, load context, compact memory, persist user message."""
    # 1. Ensure conversation
    conversation = await ensure_skill_agent_conversation(runtime, conversation_id)
    resolved_conversation_id = int(conversation["conversation_id"])

    # 2. Resolve scope
    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    scope_description = await describe_query_scope(
        runtime,
        folder_id=scope["folder_id"] if scope["scope"] == "folder" else folder_id,
        bvid=scope["bvid"] if scope["scope"] == "video" else bvid,
        scope_mode=scope_mode,
    )

    # 3. Load conversation context
    context = await build_conversation_context(
        runtime, conversation_id=resolved_conversation_id,
    )

    # 4. Compact if needed
    if should_compact_context(runtime, context):
        context = await compact_conversation_context(
            runtime, conversation_id=resolved_conversation_id, context=context,
        )

    memory_text = context.memory_text

    # 5. Persist user message
    user_message = await runtime.db.append_chat_message(
        resolved_conversation_id, role="user", content=query,
    )
    await refresh_context_stats_after_message(
        runtime, conversation_id=resolved_conversation_id, message=user_message,
    )

    # 6. Build history
    history = await build_skill_agent_history(runtime, resolved_conversation_id)

    return {
        "conversation_id": resolved_conversation_id,
        "scope": scope,
        "scope_description": scope_description,
        "memory_text": memory_text,
        "history": history,
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
        assistant_message = await runtime.db.update_chat_message(
            placeholder_message_id,
            content=normalized,
            sources=sources,
            answer_mode=answer_mode,
            route_mode=route_mode,
        )
    else:
        assistant_message = await runtime.db.append_chat_message(
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
# Build LangChain message list from history
# ---------------------------------------------------------------------------

def _build_messages(
    prompt: str,
    history: list[tuple[str, str]],
    query: str,
) -> list[Any]:
    """Build the initial message list for the agent loop."""
    messages: list[Any] = [SystemMessage(content=prompt)]
    for role, content in history:
        if role == "human":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=query))
    return messages


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
) -> tuple[list[Any], list[Any]]:
    """Build messages + tools for one agent turn. Returns (messages, tools)."""

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

    # Build prompt
    prompt = build_unified_agent_prompt(
        runtime,
        session_id=session_id,
        workspace_id=workspace_id,
        scope_description=ctx["scope_description"],
        memory_text=ctx["memory_text"],
    )

    # Build messages
    messages = _build_messages(prompt, ctx["history"], query)

    return messages, all_tools


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
    # --- Pre-processing ---
    if event_callback is not None:
        event_callback("status", {"delta": "正在准备会话上下文..."})

    ctx = await _preprocess(
        runtime,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        scope_mode=scope_mode,
        conversation_id=conversation_id,
        event_callback=event_callback,
    )
    resolved_conversation_id = ctx["conversation_id"]
    resolved_session_id = build_unified_session_id(
        conversation_id=resolved_conversation_id,
        explicit_session_id=session_id,
    )

    # --- Build workspace ---
    workspace = await ensure_skill_agent_workspace(
        runtime, conversation_id=resolved_conversation_id, actor=actor,
    )
    workspace_id = workspace["workspace_id"]

    if event_callback is not None:
        event_callback("status", {"delta": "正在加载工具与技能..."})

    # --- Build tools + messages ---
    collected_sources: list[dict[str, str]] = []
    messages, all_tools = await _build_turn_context(
        runtime,
        ctx=ctx,
        query=query,
        folder_id=folder_id,
        bvid=bvid,
        session_id=resolved_session_id,
        workspace_id=workspace_id,
        approval_mode=approval_mode,
        actor=actor,
        event_callback=event_callback,
        collected_sources=collected_sources,
    )

    # --- Run agent loop ---
    answer_text, approval_request = await _run_agent_loop(
        runtime,
        messages=messages,
        tools=all_tools,
        event_callback=event_callback,
    )

    # --- Handle HITL interrupt ---
    if approval_request is not None:
        if event_callback is not None:
            event_callback("status", {"delta": "需要人工确认后才能继续。"})
        return {
            "status": "pending_approval",
            "conversation_id": resolved_conversation_id,
            "session_id": resolved_session_id,
            "workspace_id": workspace_id,
            "approval_request": approval_request,
            "_pending_messages": messages,  # carry state for resume
            "_pending_tools": all_tools,
            "_pending_sources": collected_sources,
            "active_skills": (
                runtime.skill_service.get_active_skills(resolved_session_id)
                if runtime.skill_service
                else []
            ),
        }

    # --- Postprocess ---
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

    return {
        "status": "completed",
        "conversation_id": resolved_conversation_id,
        "session_id": resolved_session_id,
        "workspace_id": workspace_id,
        "answer": post["answer_text"],
        "answer_mode": post["answer_mode"],
        "assistant_message": post["assistant_message"],
        "sources": collected_sources,
        "active_skills": (
            runtime.skill_service.get_active_skills(resolved_session_id)
            if runtime.skill_service
            else []
        ),
    }


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
    # ── Resolve conversation ──────────────────────────────────────────────
    conversation = await ensure_skill_agent_conversation(runtime, conversation_id)
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
            {"active_skills": runtime.skill_service.get_active_skills(resolved_session_id)},
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
        )

        # ── Build workspace ───────────────────────────────────────────────
        workspace = await ensure_skill_agent_workspace(
            runtime, conversation_id=resolved_conversation_id, actor=actor,
        )
        workspace_id = workspace["workspace_id"]

        emit_event("status", {"delta": "正在加载工具与技能..."})

        # ── Build tools + messages ────────────────────────────────────────
        collected_sources: list[dict[str, str]] = []

        messages, all_tools = await _build_turn_context(
            runtime,
            ctx=ctx,
            query=query,
            folder_id=folder_id,
            bvid=bvid,
            session_id=resolved_session_id,
            workspace_id=workspace_id,
            approval_mode=approval_mode,
            actor=actor,
            event_callback=emit_event,
            collected_sources=collected_sources,
        )

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
                    emit_event=emit_event,
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
            yield make_sse_event("approval", {
                "session_id": resolved_session_id,
                "workspace_id": workspace_id,
                "approval_request": approval_request,
            })
            yield make_sse_event("skills", {
                "active_skills": (
                    runtime.skill_service.get_active_skills(resolved_session_id)
                    if runtime.skill_service else []
                ),
            })
            yield make_sse_event("done", {})
            return

        # ── Post-processing ───────────────────────────────────────────────
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

            if collected_sources:
                yield make_sse_event("sources", {"sources": collected_sources})
            yield make_sse_event("mode", {"mode": answer_mode})
            yield make_sse_event("route", {"route_mode": route_mode})
        else:
            yield make_sse_event("route", {"route_mode": "direct"})

        yield make_sse_event("skills", {
            "active_skills": (
                runtime.skill_service.get_active_skills(resolved_session_id)
                if runtime.skill_service else []
            ),
        })
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
    resolved_conversation_id = _resolve_conversation_id(session_id, conversation_id)

    # Rebuild workspace + tools (same as a fresh turn but without prepending user message)
    conversation = await ensure_skill_agent_conversation(runtime, resolved_conversation_id)
    resolved_conversation_id = int(conversation["conversation_id"])
    workspace = await ensure_skill_agent_workspace(
        runtime, conversation_id=resolved_conversation_id, actor=actor,
    )
    workspace_id = workspace["workspace_id"]

    scope = resolve_query_scope(folder_id=folder_id, bvid=bvid, scope_mode=scope_mode)
    scope_description = await describe_query_scope(
        runtime,
        folder_id=scope["folder_id"] if scope["scope"] == "folder" else folder_id,
        bvid=scope["bvid"] if scope["scope"] == "video" else bvid,
        scope_mode=scope_mode,
    )

    collected_sources: list[dict[str, str]] = []
    qa_tools = build_qa_retrieval_tools(
        runtime, folder_id=folder_id, bvid=bvid,
        event_callback=lambda et, d: (
            collected_sources.extend(d["sources"])
            if et == "sources" and d.get("sources") else None
        ),
    )
    skill_tools = build_skill_langchain_tools(
        runtime.skill_service, session_id=session_id, actor=actor,
    )
    workspace_tools = build_langchain_tools(
        runtime.tool_service, workspace_id=workspace_id, actor=actor,
    )
    all_tools = [*qa_tools, *skill_tools, *workspace_tools]
    tool_map, execute = _build_tool_executor(all_tools, runtime=runtime)

    prompt = build_unified_agent_prompt(
        runtime, session_id=session_id, workspace_id=workspace_id,
        scope_description=scope_description, memory_text="",
    )
    history = await build_skill_agent_history(runtime, resolved_conversation_id)
    messages = [SystemMessage(content=prompt)]
    for role, content in history:
        if role == "human":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))

    # Inject the approved tool call
    approved = decision
    approved_name = approved.get("name", "")
    approved_args = approved.get("args", {})
    approved_id = approved.get("id", f"resume-{approved_name}")

    # Append AIMessage with the approved tool_call
    messages.append(AIMessage(
        content="",
        tool_calls=[{"name": approved_name, "args": approved_args, "id": approved_id}],
    ))

    # Execute the approved tool
    result_str = await execute(approved_name, approved_args)
    messages.append(ToolMessage(content=result_str, tool_call_id=approved_id))

    # Continue the loop from here
    answer_text, next_approval = await _run_agent_loop(
        runtime, messages=messages, tools=all_tools,
    )

    if next_approval is not None:
        return {
            "status": "pending_approval",
            "conversation_id": resolved_conversation_id,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "approval_request": next_approval,
            "active_skills": (
                runtime.skill_service.get_active_skills(session_id)
                if runtime.skill_service else []
            ),
        }

    if not answer_text:
        answer_text = "当前没有生成有效回答。"

    answer_text = normalize_answer_citations(answer_text)
    await runtime.db.append_chat_message(
        resolved_conversation_id, role="assistant", content=answer_text,
    )

    return {
        "status": "completed",
        "conversation_id": resolved_conversation_id,
        "session_id": session_id,
        "workspace_id": workspace_id,
        "answer": answer_text,
        "active_skills": (
            runtime.skill_service.get_active_skills(session_id)
            if runtime.skill_service else []
        ),
    }


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
    normalized_conversation_id = _resolve_conversation_id(session_id, conversation_id)

    yield make_sse_event("conversation", {"conversation_id": normalized_conversation_id})
    yield make_sse_event("status", {"delta": "Agent 正在恢复执行..."})

    if runtime.skill_service is not None:
        yield make_sse_event(
            "skills",
            {"active_skills": runtime.skill_service.get_active_skills(session_id)},
        )

    queue: asyncio.Queue[tuple[str, dict[str, Any] | None] | None] = asyncio.Queue()

    def emit_event(event_type: str, data: dict[str, Any] | None = None) -> None:
        queue.put_nowait((event_type, data or {}))

    emit_event("status", {"delta": "已接收审批结果，继续执行..."})

    # Rebuild context
    conversation = await ensure_skill_agent_conversation(runtime, normalized_conversation_id)
    resolved_conversation_id = int(conversation["conversation_id"])
    workspace = await ensure_skill_agent_workspace(
        runtime, conversation_id=resolved_conversation_id, actor=actor,
    )
    workspace_id = workspace["workspace_id"]

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
        emit_event(et, d)

    qa_tools = build_qa_retrieval_tools(runtime, folder_id=folder_id, bvid=bvid, event_callback=qa_cb)
    skill_tools = build_skill_langchain_tools(
        runtime.skill_service, session_id=session_id, actor=actor, event_callback=emit_event,
    )
    workspace_tools = build_langchain_tools(
        runtime.tool_service, workspace_id=workspace_id, actor=actor, event_callback=emit_event,
    )
    all_tools = [*qa_tools, *skill_tools, *workspace_tools]
    _, execute = _build_tool_executor(all_tools, runtime=runtime, event_callback=emit_event)

    prompt = build_unified_agent_prompt(
        runtime, session_id=session_id, workspace_id=workspace_id,
        scope_description=scope_description, memory_text="",
    )
    history = await build_skill_agent_history(runtime, resolved_conversation_id)
    messages = [SystemMessage(content=prompt)]
    for role, content in history:
        if role == "human":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))

    # Inject approved tool call
    approved = decision
    approved_name = approved.get("name", "")
    approved_args = approved.get("args", {})
    approved_id = approved.get("id", f"resume-{approved_name}")

    messages.append(AIMessage(
        content="",
        tool_calls=[{"name": approved_name, "args": approved_args, "id": approved_id}],
    ))

    result_str = await execute(approved_name, approved_args)
    messages.append(ToolMessage(content=result_str, tool_call_id=approved_id))

    # ── Run streaming agent loop in background ────────────────────────────
    full_answer = ""
    next_approval: dict[str, Any] | None = None

    async def run_loop() -> None:
        nonlocal full_answer, next_approval
        try:
            full_answer, next_approval = await _stream_agent_loop(
                runtime, messages=messages, tools=all_tools, emit_event=emit_event,
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
            yield make_sse_event("approval", {
                "session_id": session_id,
                "workspace_id": workspace_id,
                "approval_request": next_approval,
            })
            yield make_sse_event("skills", {
                "active_skills": (
                    runtime.skill_service.get_active_skills(session_id)
                    if runtime.skill_service else []
                ),
            })
            yield make_sse_event("done", {})
            return

        # ── Persist & finalize ────────────────────────────────────────────
        if not full_answer:
            full_answer = "当前没有生成有效回答。"

        normalized = normalize_answer_citations(full_answer)
        await runtime.db.append_chat_message(
            resolved_conversation_id, role="assistant", content=normalized,
        )

        yield make_sse_event("skills", {
            "active_skills": (
                runtime.skill_service.get_active_skills(session_id)
                if runtime.skill_service else []
            ),
        })
        yield make_sse_event("done", {})

    except Exception as exc:
        logger.exception("Unified agent resume streaming failed")
        if full_answer:
            try:
                await runtime.db.append_chat_message(
                    resolved_conversation_id, role="assistant", content=full_answer,
                )
            except Exception:
                pass
        yield make_sse_event("error", {"detail": str(exc) or "Agent 恢复执行失败"})
