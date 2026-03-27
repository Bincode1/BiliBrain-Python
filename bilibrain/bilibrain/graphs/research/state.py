from __future__ import annotations

from typing import Any, TypedDict


class ResearchState(TypedDict, total=False):
    runtime: Any
    query: str
    folder_id: int | None
    bvid: str | None
    scope_mode: str | None
    conversation_id: int | None

    scope: dict[str, Any]
    conversation: dict[str, Any] | None
    workspace: dict[str, Any] | None

    kb_snapshot: dict[str, Any]
    kb_sources: list[dict[str, Any]]
    research_brief: dict[str, Any]
    current_queries: list[str]
    retrieval_round: int
    research_plan: dict[str, Any]
    subtasks: list[dict[str, Any]]
    retrieval_results: list[dict[str, Any]]
    analysis_results: list[dict[str, Any]]
    gap_summary: str
    sources: list[dict[str, Any]]
    retrieval_error: str

    answer_text: str
    user_message: dict[str, Any] | None
    assistant_message: dict[str, Any] | None

    current_step: str
    streaming: bool
    timings: dict[str, float]


def build_initial_research_state(
    runtime: Any,
    query: str,
    folder_id: int | None,
    bvid: str | None,
    scope_mode: str | None,
    conversation_id: int | None,
    *,
    streaming: bool = False,
) -> ResearchState:
    return {
        "runtime": runtime,
        "query": query,
        "folder_id": folder_id,
        "bvid": bvid,
        "scope_mode": scope_mode,
        "conversation_id": conversation_id,
        "streaming": streaming,
        "kb_snapshot": {},
        "kb_sources": [],
        "research_brief": {},
        "current_queries": [],
        "retrieval_round": 0,
        "research_plan": {},
        "subtasks": [],
        "retrieval_results": [],
        "analysis_results": [],
        "gap_summary": "",
        "sources": [],
        "retrieval_error": "",
        "answer_text": "",
        "user_message": None,
        "assistant_message": None,
        "current_step": "init",
        "timings": {},
    }
