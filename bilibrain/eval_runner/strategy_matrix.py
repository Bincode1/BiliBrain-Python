from __future__ import annotations


def default_strategy_matrix() -> list[dict[str, object]]:
    return [
        {
            "name": "baseline",
            "planner_enabled": True,
            "retrieval_top_k": 40,
            "rerank_top_k": 10,
        },
        {
            "name": "no_planner",
            "planner_enabled": False,
            "retrieval_top_k": 40,
            "rerank_top_k": 10,
        },
        {
            "name": "topk_20",
            "planner_enabled": True,
            "retrieval_top_k": 20,
            "rerank_top_k": 10,
        },
    ]
