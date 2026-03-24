from fastapi import Request

from bilibrain.core.runtime import Runtime


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime
