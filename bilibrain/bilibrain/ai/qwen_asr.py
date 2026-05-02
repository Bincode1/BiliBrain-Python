from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from bilibrain.ai.provider import ensure_endpoint_configured, resolve_asr_endpoint
from bilibrain.core.config import Settings

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 10 * 1024 * 1024


class RetryableAsrError(RuntimeError):
    pass


class QwenAsrClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.endpoint = resolve_asr_endpoint(settings)

    def ensure_configured(self) -> None:
        ensure_endpoint_configured(self.endpoint)

    async def transcribe(self, audio_path: Path) -> str:
        self.ensure_configured()
        normalized_path = audio_path.resolve()
        audio_bytes = await asyncio.to_thread(self._read_audio_bytes, normalized_path)
        payload = self._build_request_payload(audio_bytes, normalized_path)
        headers = {
            "Authorization": f"Bearer {self.endpoint.api_key}",
            "Content-Type": "application/json",
        }
        started = perf_counter()
        attempts = max(int(self.settings.asr_api_retries), 0) + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                logger.info(
                    "Qwen ASR request started: file=%s size=%s model=%s attempt=%s/%s",
                    normalized_path.name,
                    len(audio_bytes),
                    self.endpoint.model,
                    attempt,
                    attempts,
                )
                async with httpx.AsyncClient(
                    base_url=self.endpoint.base_url,
                    timeout=self.settings.asr_api_timeout_seconds,
                ) as client:
                    response = await client.post(
                        "/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise RetryableAsrError(
                        f"Qwen ASR request failed: status={response.status_code}, body={response.text}"
                    )
                response.raise_for_status()
                transcript = self._extract_transcript(response.json())
                logger.info(
                    "Qwen ASR request succeeded: file=%s size=%s elapsed=%.2fs attempt=%s/%s",
                    normalized_path.name,
                    len(audio_bytes),
                    perf_counter() - started,
                    attempt,
                    attempts,
                )
                return transcript
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Qwen ASR request failed: file=%s size=%s elapsed=%.2fs attempt=%s/%s error=%s",
                    normalized_path.name,
                    len(audio_bytes),
                    perf_counter() - started,
                    attempt,
                    attempts,
                    exc,
                )
                if attempt >= attempts or not self._is_retryable(exc):
                    break
                await asyncio.sleep(
                    max(int(self.settings.asr_api_retry_backoff_millis), 0) / 1000
                )

        assert last_error is not None
        raise RuntimeError(f"Qwen ASR 转写失败: {last_error}") from last_error

    def model_label(self) -> str:
        return f"api/{self.endpoint.model}"

    def _build_request_payload(
        self,
        audio_bytes: bytes,
        audio_path: Path,
    ) -> dict[str, Any]:
        data_uri = (
            f"data:{self._detect_mime_type(audio_path)};base64,"
            f"{base64.b64encode(audio_bytes).decode('ascii')}"
        )
        return {
            "model": self.endpoint.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": data_uri},
                        }
                    ],
                }
            ],
            "stream": False,
            "asr_options": {
                "language": self.settings.asr_language or "zh",
                "enable_itn": bool(self.settings.asr_enable_itn),
            },
        }

    def _extract_transcript(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Qwen ASR 没有返回可用结果")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Qwen ASR 返回内容为空")
        return content.strip()

    def _read_audio_bytes(self, audio_path: Path) -> bytes:
        audio_bytes = audio_path.read_bytes()
        if not audio_bytes:
            raise RuntimeError("待转写音频为空")
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise RuntimeError("音频分片超过 qwen3-asr-flash 的 10MB 限制")
        return audio_bytes

    def _detect_mime_type(self, audio_path: Path) -> str:
        suffix = audio_path.suffix.lower()
        if suffix == ".wav":
            return "audio/wav"
        if suffix == ".m4a":
            return "audio/mp4"
        if suffix == ".flac":
            return "audio/flac"
        if suffix == ".ogg":
            return "audio/ogg"
        return "audio/mpeg"

    def _is_retryable(self, exc: Exception) -> bool:
        return isinstance(exc, (RetryableAsrError, httpx.TimeoutException, httpx.NetworkError))
