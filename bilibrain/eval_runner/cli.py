from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from bilibrain.core.config import get_settings
from bilibrain.core.runtime import create_runtime, shutdown_runtime, startup_runtime
from bilibrain.eval_adapter import EvalRequest, run_eval_case
from eval_runner.dataset_loader import BenchmarkRow, load_benchmark_rows
from eval_runner.ragas_runner import (
    collect_benchmark_records,
    find_strategy,
    run_ragas_scoring,
    save_ragas_outputs,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BiliBrain external Ragas evaluation runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    single = subparsers.add_parser("single", help="Run one eval case")
    single.add_argument("--query", required=True)
    single.add_argument("--reference")
    single.add_argument("--folder-id", type=int)
    single.add_argument("--bvid")
    single.add_argument("--scope-mode", choices=["video", "folder", "global"])
    single.add_argument("--strategy", default="baseline")

    dataset = subparsers.add_parser("dataset", help="Run a CSV benchmark with Ragas scoring")
    dataset.add_argument("--input", required=True)
    dataset.add_argument("--strategy", default="baseline")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "single":
        return _run_single(args)
    if args.command == "dataset":
        return _run_dataset(args)
    parser.error(f"Unsupported command: {args.command}")
    return 2


def _run_single(args) -> int:
    strategy = find_strategy(args.strategy)

    request = EvalRequest(
        query=args.query,
        folder_id=args.folder_id,
        bvid=args.bvid,
        scope_mode=args.scope_mode,
        strategy_name=str(strategy.get("name") or "baseline"),
        planner_enabled=bool(strategy.get("planner_enabled", True)),
        retrieval_top_k=max(int(strategy.get("retrieval_top_k") or 40), 1),
        rerank_top_k=max(int(strategy.get("rerank_top_k") or 10), 1),
    )

    async def _run():
        runtime = create_runtime()
        await startup_runtime(runtime)
        try:
            return await run_eval_case(runtime, request)
        finally:
            await shutdown_runtime(runtime)

    result = asyncio.run(_run())
    print(json.dumps(_serialize_single_result(result), ensure_ascii=False, indent=2))
    return 0


def _run_dataset(args) -> int:
    settings = get_settings()
    strategy = find_strategy(args.strategy)
    rows = load_benchmark_rows(args.input)
    records = asyncio.run(collect_benchmark_records(rows, strategy=strategy))
    summary, scored_rows = run_ragas_scoring(
        records,
        enable_answer_relevancy=settings.ragas_enable_answer_relevancy,
        timeout_seconds=settings.ragas_run_timeout_seconds,
        max_retries=settings.ragas_run_max_retries,
        max_workers=settings.ragas_run_max_workers,
    )
    output_dir = save_ragas_outputs(
        output_root=settings.ragas_experiment_root,
        strategy_name=str(strategy.get("name") or "baseline"),
        summary=summary,
        scored_rows=scored_rows,
    )
    print(json.dumps({"output_dir": str(output_dir), **summary}, ensure_ascii=False, indent=2))
    return 0


def _serialize_single_result(result) -> dict[str, object]:
    return {
        "query": result.query,
        "response": result.response,
        "route_mode": result.route_mode,
        "retrieval_mode": result.retrieval_mode,
        "strategy_name": result.strategy_name,
        "retrieved_contexts": result.retrieved_contexts,
        "sources": result.sources,
        "timings": result.timings,
    }


if __name__ == "__main__":
    raise SystemExit(main())
