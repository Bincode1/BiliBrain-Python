from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from bilibrain.core.runtime import create_runtime, shutdown_runtime, startup_runtime
from bilibrain.eval_adapter import EvalRequest, run_eval_case
from eval_runner.dataset_loader import BenchmarkRow
from eval_runner.strategy_matrix import default_strategy_matrix


def find_strategy(name: str) -> dict[str, object]:
    for strategy in default_strategy_matrix():
        if str(strategy.get("name")) == str(name):
            return dict(strategy)
    raise ValueError(f"Unknown strategy: {name}")


async def collect_benchmark_records(
    rows: Iterable[BenchmarkRow],
    *,
    strategy: dict[str, object],
) -> list[dict[str, Any]]:
    runtime = create_runtime()
    await startup_runtime(runtime)
    try:
        records: list[dict[str, Any]] = []
        strategy_name = str(strategy.get("name") or "baseline")
        for row in rows:
            result = await run_eval_case(
                runtime,
                EvalRequest(
                    query=row.query,
                    folder_id=row.folder_id,
                    bvid=row.bvid,
                    scope_mode=row.scope_mode,
                    strategy_name=strategy_name,
                    planner_enabled=bool(strategy.get("planner_enabled", True)),
                    retrieval_top_k=max(int(strategy.get("retrieval_top_k") or 40), 1),
                    rerank_top_k=max(int(strategy.get("rerank_top_k") or 10), 1),
                ),
            )
            source_bvids = tuple(
                str(source.get("bvid") or "").strip()
                for source in result.sources
                if str(source.get("bvid") or "").strip()
            )
            records.append(
                {
                    "id": row.id,
                    "query": row.query,
                    "reference": row.reference,
                    "scope_mode": row.scope_mode,
                    "folder_id": row.folder_id,
                    "bvid": row.bvid,
                    "expected_route_mode": row.expected_route_mode,
                    "expected_source_bvids": list(row.expected_source_bvids),
                    "strategy_name": strategy_name,
                    "response": result.response,
                    "route_mode": result.route_mode,
                    "retrieval_mode": result.retrieval_mode,
                    "retrieved_contexts": list(result.retrieved_contexts),
                    "source_bvids": list(source_bvids),
                    "sources": list(result.sources),
                    "timings": dict(result.timings),
                    "route_match": (
                        result.route_mode == row.expected_route_mode
                        if row.expected_route_mode
                        else None
                    ),
                    "source_hit": (
                        any(bvid in source_bvids for bvid in row.expected_source_bvids)
                        if row.expected_source_bvids
                        else None
                    ),
                }
            )
        return records
    finally:
        await shutdown_runtime(runtime)


def run_ragas_scoring(
    records: list[dict[str, Any]],
    *,
    enable_answer_relevancy: bool = False,
    timeout_seconds: int = 120,
    max_retries: int = 3,
    max_workers: int = 4,
):
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness, FactualCorrectness, LLMContextRecall
    from ragas.run_config import RunConfig

    runtime = create_runtime()
    try:
        samples = [
            SingleTurnSample(
                user_input=str(item["query"]),
                response=str(item["response"]),
                reference=str(item["reference"]),
                retrieved_contexts=[str(text) for text in item.get("retrieved_contexts") or []],
            )
            for item in records
        ]
        dataset = EvaluationDataset(samples=samples)

        metrics = [LLMContextRecall(), Faithfulness(), FactualCorrectness()]
        evaluator_embeddings = None
        if enable_answer_relevancy:
            try:
                from ragas.metrics import AnswerRelevancy
            except ImportError:
                from ragas.metrics import ResponseRelevancy as AnswerRelevancy
            evaluator_embeddings = LangchainEmbeddingsWrapper(runtime.embedder.client)
            metrics.append(AnswerRelevancy())

        result = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=LangchainLLMWrapper(runtime.qwen.planner_base_model),
            embeddings=evaluator_embeddings,
            run_config=RunConfig(
                timeout=max(int(timeout_seconds), 1),
                max_retries=max(int(max_retries), 0),
                max_workers=max(int(max_workers), 1),
            ),
            experiment_name=f"bilibrain-ragas-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            allow_nest_asyncio=False,
            raise_exceptions=False,
            show_progress=True,
        )
    finally:
        asyncio.run(runtime.qwen.close())
        asyncio.run(runtime.embedder.close())
        runtime.vector_store.close()

    result_df = result.to_pandas() if hasattr(result, "to_pandas") else None
    scored_rows: list[dict[str, Any]] = []
    if result_df is not None:
        ragas_rows = result_df.to_dict(orient="records")
        for record, ragas_row in zip(records, ragas_rows, strict=False):
            scored_rows.append({**record, **ragas_row})
    else:
        scored_rows = list(records)

    summary = {
        "ragas_scores": dict(getattr(result, "scores", {}) or {}),
        "route_match_rate": _mean_boolean([row.get("route_match") for row in records]),
        "source_hit_rate": _mean_boolean([row.get("source_hit") for row in records]),
        "row_count": len(records),
    }
    return summary, scored_rows


def save_ragas_outputs(
    *,
    output_root: Path,
    strategy_name: str,
    summary: dict[str, Any],
    scored_rows: list[dict[str, Any]],
) -> Path:
    import pandas as pd

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = output_root / f"{timestamp}-{strategy_name}"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pd.DataFrame(scored_rows).to_csv(output_dir / "rows.csv", index=False, encoding="utf-8-sig")
    return output_dir


def _mean_boolean(values: list[object]) -> float | None:
    normalized = [1.0 if value is True else 0.0 for value in values if value is not None]
    if not normalized:
        return None
    return round(sum(normalized) / len(normalized), 6)
