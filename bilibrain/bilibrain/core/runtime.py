from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from bilibrain.ai import EmbeddingClient, QwenClient, WhisperAsrClient
from bilibrain.core.config import Settings, get_settings
from bilibrain.db.database import Database
from bilibrain.skills.service import SkillService, create_skill_service
from bilibrain.db.vector_store import LocalVectorStore
from bilibrain.services.bilibili import BilibiliClient
from bilibrain.storage import AudioStorageService
from bilibrain.tools.service import ToolService, create_tool_service


@dataclass
class Runtime:
    settings: Settings
    db: Database
    bili: BilibiliClient
    embedder: EmbeddingClient
    qwen: QwenClient
    asr: WhisperAsrClient
    audio_storage: AudioStorageService
    vector_store: LocalVectorStore
    video_tasks: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    reset_tasks: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    reset_statuses: dict[str, dict[str, Any]] = field(default_factory=dict)
    cache_tasks: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    ingestion_dispatcher_task: asyncio.Task[Any] | None = None
    ingestion_worker_id: str | None = None
    ingestion_enqueue_lock: asyncio.Lock | None = None
    reset_limiter: asyncio.Semaphore | None = None
    tool_service: ToolService | None = None
    skill_service: SkillService | None = None

    def track_cache_task(self, key: str, task: asyncio.Task[Any]) -> None:
        """Track a cache task with automatic cleanup on completion."""
        self.cache_tasks[key] = task

        def cleanup(done_task: asyncio.Task[Any]) -> None:
            self.cache_tasks.pop(key, None)
            try:
                done_task.result()
            except asyncio.CancelledError:
                return
            except Exception:
                return

        task.add_done_callback(cleanup)

    def cancel_all_cache_tasks(self) -> None:
        """Cancel and clear all cache tasks."""
        for task in list(self.cache_tasks.values()):
            task.cancel()
        self.cache_tasks.clear()


def create_runtime(settings: Settings | None = None) -> Runtime:
    resolved_settings = settings or get_settings()
    db = Database(resolved_settings)
    return Runtime(
        settings=resolved_settings,
        db=db,
        bili=BilibiliClient(resolved_settings, db),
        embedder=EmbeddingClient(resolved_settings),
        qwen=QwenClient(resolved_settings),
        asr=WhisperAsrClient(resolved_settings),
        audio_storage=AudioStorageService(resolved_settings),
        vector_store=LocalVectorStore(resolved_settings),
    )


def build_worker_id(prefix: str = "app") -> str:
    from bilibrain.services.ingestion_dispatcher import (
        build_worker_id as _build_worker_id,
    )

    return _build_worker_id(prefix)


async def run_ingestion_dispatcher(
    runtime: Runtime,
    *,
    worker_id: str,
    poll_interval: float,
    max_concurrency: int,
    stale_after_seconds: int,
) -> None:
    from bilibrain.services.ingestion_dispatcher import (
        run_ingestion_dispatcher as _run_ingestion_dispatcher,
    )

    await _run_ingestion_dispatcher(
        runtime,
        worker_id=worker_id,
        poll_interval=poll_interval,
        max_concurrency=max_concurrency,
        stale_after_seconds=stale_after_seconds,
    )


async def startup_runtime(runtime: Runtime) -> None:
    runtime.settings.audio_dir.mkdir(parents=True, exist_ok=True)
    runtime.settings.vector_db_dir.mkdir(parents=True, exist_ok=True)
    runtime.settings.tools_workspace_root.mkdir(parents=True, exist_ok=True)
    runtime.settings.skills_root.mkdir(parents=True, exist_ok=True)
    await runtime.db.ensure_ready()
    runtime.tool_service = create_tool_service(runtime.settings, runtime.db)
    runtime.skill_service = create_skill_service(runtime.settings, runtime.db)
    # 从数据库加载激活的技能
    if runtime.skill_service:
        await runtime.skill_service._load_active_skills()
    runtime.ingestion_enqueue_lock = asyncio.Lock()
    runtime.reset_limiter = asyncio.Semaphore(
        max(int(runtime.settings.reset_max_concurrency), 1)
    )
    runtime.ingestion_worker_id = build_worker_id("app")
    runtime.ingestion_dispatcher_task = asyncio.create_task(
        run_ingestion_dispatcher(
            runtime,
            worker_id=runtime.ingestion_worker_id,
            poll_interval=runtime.settings.ingestion_poll_interval_seconds,
            max_concurrency=runtime.settings.ingestion_max_concurrency,
            stale_after_seconds=runtime.settings.ingestion_task_stale_after_seconds,
        )
    )


async def shutdown_runtime(runtime: Runtime) -> None:
    if runtime.ingestion_dispatcher_task is not None:
        runtime.ingestion_dispatcher_task.cancel()
    for task in list(runtime.video_tasks.values()):
        task.cancel()
    for task in list(runtime.reset_tasks.values()):
        task.cancel()
    for task in list(runtime.cache_tasks.values()):
        task.cancel()

    all_tasks = []
    if runtime.ingestion_dispatcher_task is not None:
        all_tasks.append(runtime.ingestion_dispatcher_task)
    all_tasks.extend(runtime.video_tasks.values())
    all_tasks.extend(runtime.reset_tasks.values())
    all_tasks.extend(runtime.cache_tasks.values())
    if all_tasks:
        await asyncio.gather(*all_tasks, return_exceptions=True)

    runtime.video_tasks.clear()
    runtime.reset_tasks.clear()
    runtime.reset_statuses.clear()
    runtime.cache_tasks.clear()
    await runtime.bili.close()
    await runtime.embedder.close()
    await runtime.qwen.close()
    await runtime.asr.close()
    runtime.vector_store.close()
