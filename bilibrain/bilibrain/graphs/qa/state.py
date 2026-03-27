from __future__ import annotations

from typing import Any, TypedDict, Annotated

from langgraph.graph.message import add_messages


class QAState(TypedDict, total=False):
    runtime: Any
    query: str
    folder_id: int | None
    bvid: str | None
    scope_mode: str | None
    conversation_id: int | None

    scope: dict[str, Any]
    conversation: dict[str, Any]
    context: dict[str, Any]
    memory_text: str
    recent_history: list[dict[str, Any]]

    query_plan: Any
    route_mode: str | None
    retrieval_mode: str | None
    use_history: bool

    matches: list[dict[str, Any]]
    documents: list[dict[str, Any]] | None
    sources: list[dict[str, str]]

    answer_text: str

    user_message: dict[str, Any] | None
    assistant_message: dict[str, Any] | None

    current_step: str
    error: str | None

    streaming: bool
    execution_policy: dict[str, Any]
    timings: dict[str, float]

    use_summaries: bool

    messages: Annotated[list[Any], add_messages]


def build_initial_qa_state(
    runtime: Any,
    query: str,
    folder_id: int | None,
    bvid: str | None,
    scope_mode: str | None,
    conversation_id: int | None,
    *,
    execution_policy: dict[str, Any] | None = None,
    streaming: bool = False,
) -> QAState:
    return {
        "runtime": runtime,
        "query": query,
        "folder_id": folder_id,
        "bvid": bvid,
        "scope_mode": scope_mode,
        "conversation_id": conversation_id,
        "streaming": streaming,
        "execution_policy": dict(execution_policy or {}),
        "current_step": "init",
        "recent_history": [],
        "memory_text": "",
        "sources": [],
        "matches": [],
        "documents": None,
        "user_message": None,
        "assistant_message": None,
        "use_summaries": False,
        "timings": {},
        "messages": [],
    }
