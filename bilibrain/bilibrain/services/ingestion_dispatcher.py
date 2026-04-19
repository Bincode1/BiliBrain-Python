from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from typing import Any

from bilibrain.graphs.ingestion import run_ingestion_graph

logger = logging.getLogger(__name__)

_DISPATCHER_LOCK_KEY = "ingestion_dispatcher_lock"
_DISPATCHER_LOCK_LEASE_SECONDS = 30


def build_worker_id(prefix: str = "app") -> str:
    host = socket.gethostname().split(".")[0]
    pid = os.getpid()
    suffix = uuid.uuid4().hex[:8]
    return f"{prefix}-{host}-{pid}-{suffix}"[:64]


def _heartbeat_interval_seconds(stale_after_seconds: int) -> float:
    return max(min(float(stale_after_seconds) / 3.0, 30.0), 1.0)


async def _heartbeat_ingestion_task(
    runtime, *, task_id: int, worker_id: str, stale_after_seconds: int
) -> None:
    interval_seconds = _heartbeat_interval_seconds(stale_after_seconds)

    while True:
        await asyncio.sleep(interval_seconds)
        await runtime.db.touch_ingestion_task_lock(task_id, worker_id=worker_id)


async def process_ingestion_task(
    runtime, task_row: dict[str, Any], *, worker_id: str, stale_after_seconds: int
) -> None:
    task_id = int(task_row["task_id"])
    bvid = str(task_row["bvid"])
    heartbeat_task = asyncio.create_task(
        _heartbeat_ingestion_task(
            runtime,
            task_id=task_id,
            worker_id=worker_id,
            stale_after_seconds=stale_after_seconds,
        )
    )
    try:
        await run_ingestion_graph(runtime, bvid)
    except Exception as exc:
        await runtime.db.mark_ingestion_task_failed(task_id, str(exc))
        raise
    else:
        await runtime.db.mark_ingestion_task_succeeded(task_id)
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


async def run_ingestion_dispatcher(
    runtime,
    *,
    worker_id: str,
    poll_interval: float,
    max_concurrency: int,
    stale_after_seconds: int,
) -> None:
    active_tasks: dict[asyncio.Task[Any], str] = {}
    safe_concurrency = max(int(max_concurrency), 1)
    safe_poll_interval = max(float(poll_interval), 0.2)
    lease_owned = False

    def cleanup_task(done_task: asyncio.Task[Any]) -> None:
        bvid = active_tasks.pop(done_task, None)
        if bvid:
            runtime.video_tasks.pop(bvid, None)
        try:
            done_task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            return

    try:
        while True:
            renewed = await runtime.db.try_acquire_state_lease(
                key=_DISPATCHER_LOCK_KEY,
                owner=worker_id,
                lease_seconds=_DISPATCHER_LOCK_LEASE_SECONDS,
            )
            if not renewed:
                if lease_owned:
                    logger.warning("Ingestion dispatcher lease lost for %s, pausing consumer loop", worker_id)
                    lease_owned = False
                await asyncio.sleep(safe_poll_interval)
                continue
            if not lease_owned:
                logger.info("Ingestion dispatcher lease acquired by %s", worker_id)
                lease_owned = True

            await runtime.db.mark_stale_ingestion_tasks(
                stale_after_seconds=stale_after_seconds,
                limit=max(safe_concurrency * 4, 20),
            )

            while len(active_tasks) < safe_concurrency:
                claimed = await runtime.db.claim_next_ingestion_task(
                    worker_id=worker_id,
                    stale_after_seconds=stale_after_seconds,
                )
                if not claimed:
                    break
                bvid = str(claimed["bvid"])
                logger.info("Claimed ingestion task for %s (task_id=%s)", bvid, claimed["task_id"])
                task = asyncio.create_task(
                    process_ingestion_task(
                        runtime,
                        claimed,
                        worker_id=worker_id,
                        stale_after_seconds=stale_after_seconds,
                    )
                )
                active_tasks[task] = bvid
                runtime.video_tasks[bvid] = task
                task.add_done_callback(cleanup_task)

            if active_tasks:
                await asyncio.wait(
                    active_tasks.keys(),
                    timeout=safe_poll_interval,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                continue

            await asyncio.sleep(safe_poll_interval)
    finally:
        for task in list(active_tasks.keys()):
            if not task.done():
                task.cancel()
        if active_tasks:
            await asyncio.gather(*active_tasks.keys(), return_exceptions=True)
        if lease_owned:
            await runtime.db.release_state_lease(
                key=_DISPATCHER_LOCK_KEY,
                owner=worker_id,
            )
