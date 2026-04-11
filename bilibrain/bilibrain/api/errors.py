import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DatabaseError


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RuntimeError)
    async def handle_runtime_error(_, exc: RuntimeError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(httpx.HTTPError)
    async def handle_http_error(_, exc: httpx.HTTPError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(DatabaseError)
    async def handle_db_error(_, exc: DatabaseError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": f"数据库连接或查询失败：{exc}"})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc) or "Internal Server Error"})
