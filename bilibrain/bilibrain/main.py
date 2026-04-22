from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from bilibrain.api.errors import register_exception_handlers
from bilibrain.api.router import api_router
from bilibrain.core.config import get_settings
from bilibrain.core.runtime import create_runtime, shutdown_runtime, startup_runtime


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://localhost:5176"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    assets_dir = settings.frontend_dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/storage/audio", StaticFiles(directory=settings.audio_dir), name="audio-storage")

    return app


app = create_app()
