from __future__ import annotations

import asyncio
import logging
from typing import Any

from bilibrain.ai.provider import (
    build_langchain_embedding_model,
    ensure_endpoint_configured,
    resolve_embedding_endpoint,
)
from bilibrain.core.config import Settings

logger = logging.getLogger(__name__)

MAX_EMBEDDING_INPUT_TOKENS = 8192
MAX_BATCH_TOTAL_TOKENS = 8192
EMBEDDING_CONCURRENCY = 3


def _estimate_tokens(text: str) -> int:
    return max(len(text), int(len(text.encode("utf-8")) / 1.5))


class EmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.endpoint = resolve_embedding_endpoint(settings)
        self._embedder: Any | None = None

    def ensure_configured(self) -> None:
        ensure_endpoint_configured(self.endpoint)

    def _truncate(self, text: str) -> str:
        estimated = _estimate_tokens(text)
        if estimated <= MAX_EMBEDDING_INPUT_TOKENS:
            return text
        ratio = MAX_EMBEDDING_INPUT_TOKENS / estimated
        cut = max(1, int(len(text) * ratio * 0.95))
        logger.warning(
            "Truncating embedding input: %d estimated tokens > %d, cutting to ~%d chars",
            estimated,
            MAX_EMBEDDING_INPUT_TOKENS,
            cut,
        )
        return text[:cut]

    def _build_batches(self, texts: list[str]) -> list[list[str]]:
        batches: list[list[str]] = []
        batch: list[str] = []
        batch_tokens = 0
        for text in texts:
            tokens = _estimate_tokens(text)
            if batch and (batch_tokens + tokens > MAX_BATCH_TOTAL_TOKENS):
                batches.append(batch)
                batch = []
                batch_tokens = 0
            batch.append(text)
            batch_tokens += tokens
        if batch:
            batches.append(batch)
        return batches

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        return await self._get_embedder().aembed_documents(batch)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.ensure_configured()
        if not texts:
            return []
        truncated = [self._truncate(t) if t else " " for t in texts]
        batches = self._build_batches(truncated)
        if len(batches) > 1:
            logger.info(
                "Embedding %d texts split into %d batches (max %d tokens/batch)",
                len(texts),
                len(batches),
                MAX_BATCH_TOTAL_TOKENS,
            )
        semaphore = asyncio.Semaphore(EMBEDDING_CONCURRENCY)

        async def _limited(idx: int, batch: list[str]) -> tuple[int, list[list[float]]]:
            async with semaphore:
                result = await self._embed_batch(batch)
                return idx, result

        tasks = [_limited(i, b) for i, b in enumerate(batches)]
        completed = await asyncio.gather(*tasks)
        ordered = sorted(completed, key=lambda x: x[0])
        embeddings: list[list[float]] = []
        for _, batch_result in ordered:
            embeddings.extend(batch_result)
        return embeddings

    def _get_embedder(self):
        if self._embedder is None:
            self._embedder = build_langchain_embedding_model(
                self.endpoint,
                dimensions=self.settings.embedding_dimension,
            )
        return self._embedder

    async def close(self) -> None:
        return None
