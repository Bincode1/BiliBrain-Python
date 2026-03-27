from __future__ import annotations

import argparse
import asyncio

from bilibrain.core.runtime import create_runtime, shutdown_runtime, startup_runtime
from bilibrain.services.ingestion_dispatcher import build_worker_id, run_ingestion_dispatcher


async def worker_loop(*, poll_interval: float, max_concurrency: int, stale_after_seconds: int) -> None:
    runtime = create_runtime()
    await startup_runtime(runtime)
    worker_id = build_worker_id("worker")

    try:
        if runtime.ingestion_dispatcher_task is not None:
            runtime.ingestion_dispatcher_task.cancel()
            await asyncio.gather(runtime.ingestion_dispatcher_task, return_exceptions=True)
            runtime.ingestion_dispatcher_task = None

        await run_ingestion_dispatcher(
            runtime,
            worker_id=worker_id,
            poll_interval=poll_interval,
            max_concurrency=max_concurrency,
            stale_after_seconds=stale_after_seconds,
        )
    finally:
        await shutdown_runtime(runtime)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BiliBrain ingestion worker")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--stale-after-seconds", type=int, default=1800)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(
        worker_loop(
            poll_interval=args.poll_interval,
            max_concurrency=args.max_concurrency,
            stale_after_seconds=args.stale_after_seconds,
        )
    )


if __name__ == "__main__":
    main()
