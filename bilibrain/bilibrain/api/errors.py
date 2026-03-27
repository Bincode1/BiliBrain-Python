import httpx
import pymysql
from fastapi import FastAPI
from fastapi.responses import JSONResponse


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RuntimeError)
    async def handle_runtime_error(_, exc: RuntimeError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(httpx.HTTPError)
    async def handle_http_error(_, exc: httpx.HTTPError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(pymysql.MySQLError)
    async def handle_mysql_error(_, exc: pymysql.MySQLError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": f"MySQL 连接或查询失败：{exc}"})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc) or "Internal Server Error"})
