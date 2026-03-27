from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvalRequest:
    query: str
    folder_id: int | None = None
    bvid: str | None = None
    scope_mode: str | None = None
    strategy_name: str = "baseline"
    persist_messages: bool = False
    load_history: bool = False
    planner_enabled: bool = True
    retrieval_top_k: int = 40
    rerank_top_k: int = 10


@dataclass(frozen=True)
class EvalExecutionPolicy:
    persist_messages: bool = False
    load_history: bool = False
    planner_enabled: bool = True
    retrieval_top_k: int = 40
    rerank_top_k: int = 10


@dataclass(frozen=True)
class EvalTrace:
    route_mode: str | None
    retrieval_mode: str | None
    retrieved_contexts: list[str] = field(default_factory=list)
    retrieved_items: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalResult:
    query: str
    response: str
    route_mode: str | None
    retrieval_mode: str | None
    strategy_name: str
    conversation_id: int | None = None
    retrieved_contexts: list[str] = field(default_factory=list)
    retrieved_items: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
