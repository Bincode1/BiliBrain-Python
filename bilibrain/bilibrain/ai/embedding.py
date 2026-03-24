from __future__ import annotations

import asyncio

from langchain_ollama import OllamaEmbeddings

from bilibrain.core.config import Settings


class EmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OllamaEmbeddings(
            model=settings.embedding_model,
            base_url=settings.ollama_base_url,
        )

    def ensure_configured(self) -> None:
        if not self.settings.embedding_model:
            raise RuntimeError("EMBEDDING_MODEL not set")

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.ensure_configured()
        embeddings = await asyncio.to_thread(self.client.embed_documents, texts)
        if not isinstance(embeddings, list):
            raise RuntimeError("Ollama embedding returned invalid format")
        return embeddings

    async def close(self) -> None:
        return None
