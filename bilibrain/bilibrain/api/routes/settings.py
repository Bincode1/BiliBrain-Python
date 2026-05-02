from __future__ import annotations

from fastapi import APIRouter, Depends

from bilibrain.ai.provider import infer_provider_kind, normalize_ollama_base_url, resolve_asr_endpoint, resolve_chat_endpoint, resolve_embedding_endpoint
from bilibrain.api.deps import get_runtime
from bilibrain.core.env_writer import write_env
from bilibrain.core.runtime import Runtime
from bilibrain.schemas.requests import ModelEndpointSettings, ModelSettingsRequest, ModelSettingsResponse

router = APIRouter()

_API_KEY_SENTINEL = "__REDACTED__"

_ENDPOINT_ENV_MAP = {
    "chat": {
        "model": "CHAT_API_MODEL",
        "base_url": "CHAT_API_BASE_URL",
        "api_key": "CHAT_API_KEY",
        "legacy_model": "LLM_MODEL",
    },
    "embedding": {
        "model": "EMBEDDING_API_MODEL",
        "base_url": "EMBEDDING_API_BASE_URL",
        "api_key": "EMBEDDING_API_KEY",
        "legacy_model": "EMBEDDING_MODEL",
    },
    "asr": {
        "model": "ASR_API_MODEL",
        "base_url": "ASR_API_BASE_URL",
        "api_key": "ASR_API_KEY",
    },
}


def _mask_api_key(value: str) -> str:
    return _API_KEY_SENTINEL if value else ""


def _build_endpoint_response(endpoint) -> ModelEndpointSettings:
    return ModelEndpointSettings(
        model=endpoint.model,
        base_url=endpoint.base_url,
        api_key=_mask_api_key(endpoint.api_key),
    )


@router.get("/api/settings/models", response_model=ModelSettingsResponse)
async def get_model_settings(
    runtime: Runtime = Depends(get_runtime),
) -> ModelSettingsResponse:
    settings = runtime.settings
    return ModelSettingsResponse(
        chat=_build_endpoint_response(resolve_chat_endpoint(settings)),
        embedding=_build_endpoint_response(resolve_embedding_endpoint(settings)),
        asr=_build_endpoint_response(resolve_asr_endpoint(settings)),
    )


def _collect_endpoint_updates(name: str, payload: ModelEndpointSettings) -> dict[str, str]:
    env_map = _ENDPOINT_ENV_MAP[name]
    updates = {
        env_map["model"]: payload.model,
        env_map["base_url"]: payload.base_url,
    }
    api_key = payload.api_key
    if api_key != _API_KEY_SENTINEL:
        updates[env_map["api_key"]] = api_key
    legacy_model_key = env_map.get("legacy_model")
    if legacy_model_key:
        updates[legacy_model_key] = payload.model
    return updates


def _preferred_ollama_base_url(payload: ModelSettingsRequest) -> str:
    for endpoint in (payload.chat, payload.embedding):
        if infer_provider_kind(endpoint.base_url) == "ollama":
            return normalize_ollama_base_url(endpoint.base_url)
    return ""


@router.post("/api/settings/models")
async def update_model_settings(
    payload: ModelSettingsRequest,
) -> dict[str, bool]:
    updates: dict[str, str] = {}
    updates.update(_collect_endpoint_updates("chat", payload.chat))
    updates.update(_collect_endpoint_updates("embedding", payload.embedding))
    updates.update(_collect_endpoint_updates("asr", payload.asr))
    ollama_base_url = _preferred_ollama_base_url(payload)
    if ollama_base_url:
        updates["OLLAMA_BASE_URL"] = ollama_base_url
    await write_env(updates)
    return {"ok": True, "restart_required": True}
