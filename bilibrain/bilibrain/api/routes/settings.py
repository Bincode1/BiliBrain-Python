from __future__ import annotations

from fastapi import APIRouter, Depends

from bilibrain.api.deps import get_runtime
from bilibrain.core.env_writer import write_env
from bilibrain.core.runtime import Runtime
from bilibrain.schemas.requests import ModelSettingsRequest, ModelSettingsResponse

router = APIRouter()

_ENV_KEY_MAP = {
    "llm_model": "LLM_MODEL",
    "dashscope_api_key": "DASHSCOPE_API_KEY",
    "dashscope_base_url": "DASHSCOPE_BASE_URL",
    "embedding_model": "EMBEDDING_MODEL",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "asr_api_model": "ASR_API_MODEL",
    "asr_api_base_url": "ASR_API_BASE_URL",
}


@router.get("/api/settings/models", response_model=ModelSettingsResponse)
async def get_model_settings(
    runtime: Runtime = Depends(get_runtime),
) -> ModelSettingsResponse:
    s = runtime.settings
    return ModelSettingsResponse(
        llm_model=s.llm_model,
        dashscope_api_key=s.dashscope_api_key,
        dashscope_base_url=s.dashscope_base_url,
        embedding_model=s.embedding_model,
        ollama_base_url=s.ollama_base_url,
        asr_api_model=s.asr_api_model,
        asr_api_base_url=s.asr_api_base_url,
    )


@router.post("/api/settings/models")
async def update_model_settings(
    payload: ModelSettingsRequest,
) -> dict[str, bool]:
    updates = {
        _ENV_KEY_MAP[field]: value
        for field, value in payload.model_dump().items()
    }
    await write_env(updates)
    return {"ok": True, "restart_required": True}
