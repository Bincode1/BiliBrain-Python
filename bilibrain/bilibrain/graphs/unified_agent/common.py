from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime as GraphRuntime

from bilibrain.graphs.unified_agent.state import UnifiedAgentContext, UnifiedAgentState
from bilibrain.services.runtime_events import build_persisting_runtime_event_callback
from bilibrain.services import unified_agent as legacy_unified_agent


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stream_writer():
    try:
        return get_stream_writer()
    except Exception:
        return None


def emit_stream(event_type: str, data: dict[str, Any] | None = None) -> None:
    writer = stream_writer()
    if writer is not None:
        writer({"event_type": event_type, "data": data or {}})


def build_event_callback(
    state: UnifiedAgentState,
    runtime: GraphRuntime[UnifiedAgentContext],
):
    context = runtime.context or {}
    app_runtime = context["runtime"]
    tasks = context.get("persisted_event_tasks") or []
    return build_persisting_runtime_event_callback(
        app_runtime,
        conversation_id=int(state["conversation_id"]),
        workspace_id=str(state.get("workspace_id") or "default"),
        downstream=emit_stream,
        tasks=tasks,
        task_id=str(state.get("task_id") or "").strip() or None,
    )


def build_skills_state(runtime, session_id: str) -> dict[str, Any]:
    if getattr(runtime, "skill_service", None) is None:
        return {"active_skills": [], "loaded_skills": []}
    return {
        "active_skills": runtime.skill_service.get_active_skills(session_id),
        "loaded_skills": runtime.skill_service.get_loaded_skills(session_id),
    }


def extract_text_from_content(content: Any) -> str:
    return legacy_unified_agent._extract_text_from_content(content)


def tool_name(tool: Any) -> str:
    return getattr(tool, "name", None) or getattr(getattr(tool, "func", None), "__name__", "")


def normalize_tool_result(result: Any) -> tuple[str, dict[str, Any] | None]:
    if hasattr(result, "model_dump"):
        dumped = result.model_dump()
        return json.dumps(dumped, ensure_ascii=False), dumped if isinstance(dumped, dict) else None
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return result, None
        return result, parsed if isinstance(parsed, dict) else None
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False), result
    return str(result), None


def merge_collected_sources(
    existing: list[dict[str, str]],
    new_sources: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged = list(existing)
    seen = {
        (
            str(item.get("ref_index") or ""),
            str(item.get("bvid") or ""),
            str(item.get("timestamp") or ""),
            str(item.get("excerpt") or ""),
        )
        for item in merged
        if isinstance(item, dict)
    }
    for item in new_sources:
        key = (
            str(item.get("ref_index") or ""),
            str(item.get("bvid") or ""),
            str(item.get("timestamp") or ""),
            str(item.get("excerpt") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def merge_decision_args(action: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    merged = dict(action.get("args") or {})
    decision_args = decision.get("args")
    if isinstance(decision_args, dict):
        merged.update(decision_args)
    return merged
