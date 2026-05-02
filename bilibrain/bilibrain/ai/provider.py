from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from bilibrain.core.config import Settings

ProviderKind = Literal["ollama", "openai_compatible"]
CapabilityKind = Literal["chat", "embedding", "asr"]

_OLLAMA_LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}
_OLLAMA_DEFAULT_PORT = 11434


@dataclass(frozen=True)
class ModelEndpoint:
    capability: CapabilityKind
    model: str
    base_url: str
    api_key: str
    provider: ProviderKind

    @property
    def requires_api_key(self) -> bool:
        return self.provider != "ollama"


def normalize_base_url(url: str | None) -> str:
    return str(url or "").strip().rstrip("/")


def normalize_ollama_base_url(url: str | None) -> str:
    normalized = normalize_base_url(url)
    for suffix in ("/v1", "/api"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def infer_provider_kind(base_url: str | None) -> ProviderKind:
    normalized = normalize_base_url(base_url)
    if not normalized:
        return "openai_compatible"
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower()
    port = parsed.port
    path = parsed.path.rstrip("/")
    if port == _OLLAMA_DEFAULT_PORT:
        return "ollama"
    if host in _OLLAMA_LOCAL_HOSTS and path in {"", "/", "/api", "/v1"} and port in {None, _OLLAMA_DEFAULT_PORT}:
        return "ollama"
    return "openai_compatible"


def _is_deepseek_compatible_endpoint(endpoint: ModelEndpoint) -> bool:
    parsed = urlparse(normalize_base_url(endpoint.base_url))
    host = (parsed.hostname or "").lower()
    model = str(endpoint.model or "").strip().lower()
    return "deepseek" in host or model.startswith("deepseek")


def _looks_like_ollama_model(model: str) -> bool:
    return ":" in str(model or "").strip()


def _field(settings: Settings, name: str) -> str:
    return str(getattr(settings, name, "") or "").strip()


def _resolve_endpoint(
    *,
    capability: CapabilityKind,
    model: str | None,
    primary_base_url: str | None,
    legacy_base_url: str | None = None,
    primary_api_key: str | None = None,
    legacy_api_key: str | None = None,
    ollama_fallback_base_url: str | None = None,
) -> ModelEndpoint:
    resolved_model = str(model or "").strip()
    resolved_base_url = normalize_base_url(primary_base_url)
    if not resolved_base_url and _looks_like_ollama_model(resolved_model):
        resolved_base_url = normalize_base_url(ollama_fallback_base_url)
    if not resolved_base_url:
        resolved_base_url = normalize_base_url(legacy_base_url)
    provider = infer_provider_kind(resolved_base_url)
    if provider == "ollama":
        resolved_api_key = ""
    else:
        resolved_api_key = str(primary_api_key or legacy_api_key or "").strip()
    return ModelEndpoint(
        capability=capability,
        model=resolved_model,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        provider=provider,
    )


def resolve_chat_endpoint(settings: Settings) -> ModelEndpoint:
    return _resolve_endpoint(
        capability="chat",
        model=_field(settings, "chat_api_model") or _field(settings, "llm_model"),
        primary_base_url=_field(settings, "chat_api_base_url"),
        legacy_base_url=_field(settings, "dashscope_base_url"),
        primary_api_key=_field(settings, "chat_api_key"),
        legacy_api_key=_field(settings, "dashscope_api_key"),
        ollama_fallback_base_url=_field(settings, "ollama_base_url"),
    )


def resolve_embedding_endpoint(settings: Settings) -> ModelEndpoint:
    return _resolve_endpoint(
        capability="embedding",
        model=_field(settings, "embedding_api_model") or _field(settings, "embedding_model"),
        primary_base_url=_field(settings, "embedding_api_base_url"),
        legacy_base_url=_field(settings, "dashscope_base_url"),
        primary_api_key=_field(settings, "embedding_api_key"),
        legacy_api_key=_field(settings, "dashscope_api_key"),
        ollama_fallback_base_url=_field(settings, "ollama_base_url"),
    )


def resolve_asr_endpoint(settings: Settings) -> ModelEndpoint:
    return ModelEndpoint(
        capability="asr",
        model=_field(settings, "asr_api_model"),
        base_url=normalize_base_url(_field(settings, "asr_api_base_url") or _field(settings, "dashscope_base_url")),
        api_key=_field(settings, "asr_api_key") or _field(settings, "dashscope_api_key"),
        provider="openai_compatible",
    )


def ensure_endpoint_configured(endpoint: ModelEndpoint) -> None:
    if not endpoint.model:
        raise RuntimeError(f"{endpoint.capability.upper()} model not set")
    if not endpoint.base_url:
        raise RuntimeError(f"{endpoint.capability.upper()} base URL not set")
    if endpoint.requires_api_key and not endpoint.api_key:
        raise RuntimeError(f"{endpoint.capability.upper()} API key not set")


def build_langchain_chat_model(endpoint: ModelEndpoint):
    if endpoint.provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ModuleNotFoundError as exc:
            raise RuntimeError("langchain_ollama is not installed") from exc
        return ChatOllama(
            model=endpoint.model,
            base_url=normalize_ollama_base_url(endpoint.base_url),
            temperature=0,
            reasoning=False,
        )

    try:
        from langchain_openai import ChatOpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("langchain_openai is not installed") from exc
    extra_body = None
    if _is_deepseek_compatible_endpoint(endpoint):
        extra_body = {"thinking": {"type": "disabled"}}
    return ChatOpenAI(
        model=endpoint.model,
        api_key=endpoint.api_key,
        base_url=endpoint.base_url,
        temperature=0,
        streaming=True,
        extra_body=extra_body,
    )


def build_langchain_embedding_model(endpoint: ModelEndpoint, *, dimensions: int):
    if endpoint.provider == "ollama":
        try:
            from langchain_ollama import OllamaEmbeddings
        except ModuleNotFoundError as exc:
            raise RuntimeError("langchain_ollama is not installed") from exc
        return OllamaEmbeddings(
            model=endpoint.model,
            base_url=normalize_ollama_base_url(endpoint.base_url),
        )

    try:
        from langchain_openai import OpenAIEmbeddings
    except ModuleNotFoundError as exc:
        raise RuntimeError("langchain_openai is not installed") from exc
    return OpenAIEmbeddings(
        model=endpoint.model,
        api_key=endpoint.api_key,
        base_url=endpoint.base_url,
        dimensions=dimensions,
    )
