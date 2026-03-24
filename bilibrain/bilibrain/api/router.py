from fastapi import APIRouter

from bilibrain.api.routes import auth, folders, qa, system, videos


api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(folders.router)
api_router.include_router(videos.router)
api_router.include_router(qa.router)
