from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bilibrain.api.errors import register_exception_handlers
from bilibrain.api.router import api_router
from bilibrain.core.config import get_settings
from bilibrain.core.runtime import create_runtime, shutdown_runtime, startup_runtime


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = create_runtime(settings)
        app.state.runtime = runtime
        await startup_runtime(runtime)
        try:
            yield
        finally:
            await shutdown_runtime(runtime)

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_exception_handlers(app)
    app.include_router(api_router)

    assets_dir = settings.frontend_dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    if settings.audio_cache_dir.exists() or settings.audio_storage_provider == "local":
        settings.audio_cache_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/storage/audio", StaticFiles(directory=settings.audio_cache_dir), name="audio-storage")

    return app


app = create_app()
