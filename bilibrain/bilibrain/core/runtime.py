from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from bilibrain.ai import AsrClient, EmbeddingClient, QwenClient
from bilibrain.core.config import Settings, get_settings
from bilibrain.db.database import Database
from bilibrain.db.vector_store import MilvusStore
from bilibrain.services.bilibili import BilibiliClient
from bilibrain.storage import AudioStorageService, create_audio_storage_service


@dataclass
class Runtime:
    settings: Settings
    db: Database
    bili: BilibiliClient
    embedder: EmbeddingClient
    qwen: QwenClient
    asr: AsrClient
    audio_storage: AudioStorageService
    vector_store: MilvusStore
    video_tasks: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    cache_tasks: dict[str, asyncio.Task[Any]] = field(default_factory=dict)


def create_runtime(settings: Settings | None = None) -> Runtime:
    resolved_settings = settings or get_settings()
    db = Database(resolved_settings)
    return Runtime(
        settings=resolved_settings,
        db=db,
        bili=BilibiliClient(resolved_settings, db),
        embedder=EmbeddingClient(resolved_settings),
        qwen=QwenClient(resolved_settings),
        asr=AsrClient(resolved_settings),
        audio_storage=create_audio_storage_service(resolved_settings),
        vector_store=MilvusStore(resolved_settings),
    )


async def startup_runtime(runtime: Runtime) -> None:
    runtime.settings.audio_cache_dir.mkdir(parents=True, exist_ok=True)
    runtime.db.ensure_ready()


async def shutdown_runtime(runtime: Runtime) -> None:
    for task in list(runtime.video_tasks.values()):
        task.cancel()
    for task in list(runtime.cache_tasks.values()):
        task.cancel()
    if runtime.video_tasks:
        await asyncio.gather(*runtime.video_tasks.values(), return_exceptions=True)
    if runtime.cache_tasks:
        await asyncio.gather(*runtime.cache_tasks.values(), return_exceptions=True)
    await runtime.bili.close()
    await runtime.embedder.close()
    await runtime.qwen.close()
    await runtime.asr.close()
    runtime.vector_store.close()
