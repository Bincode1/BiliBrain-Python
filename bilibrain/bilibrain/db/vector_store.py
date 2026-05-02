from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from bilibrain.core.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_RRF_DENSE_WEIGHT = 0.05
DEFAULT_RRF_BM25_WEIGHT = 0.95
DEFAULT_RRF_K = 10


@dataclass(frozen=True)
class _SearchResult:
    id: str
    score: float


@dataclass(frozen=True)
class _BM25Snapshot:
    """Immutable snapshot of the BM25 index. Readers never need a lock."""
    corpus_ids: tuple[str, ...]
    corpus_texts: tuple[str, ...]
    bvid_chunks: dict[str, tuple[str, ...]]
    bm25: Any  # BM25Okapi | None


def _tokenize(text: str) -> list[str]:
    import jieba

    return list(jieba.cut(text))


def _build_bm25_snapshot(
    corpus_ids: list[str],
    corpus_texts: list[str],
    metadatas: list[dict[str, Any] | None],
) -> _BM25Snapshot:
    """Tokenize corpus and build BM25 index — pure computation, no locks."""
    from rank_bm25 import BM25Okapi

    tokenized = [_tokenize(t) for t in corpus_texts]
    bm25 = BM25Okapi(tokenized) if tokenized else None

    bvid_chunks: dict[str, list[str]] = {}
    for chunk_id, meta in zip(corpus_ids, metadatas):
        bvid = (meta or {}).get("bvid", "")
        if bvid:
            bvid_chunks.setdefault(bvid, []).append(chunk_id)

    return _BM25Snapshot(
        corpus_ids=tuple(corpus_ids),
        corpus_texts=tuple(corpus_texts),
        bvid_chunks={k: tuple(v) for k, v in bvid_chunks.items()},
        bm25=bm25,
    )


def rrf_merge(
    dense_results: list[_SearchResult],
    bm25_results: list[_SearchResult],
    dense_weight: float = DEFAULT_RRF_DENSE_WEIGHT,
    bm25_weight: float = DEFAULT_RRF_BM25_WEIGHT,
    k: int = DEFAULT_RRF_K,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for rank, item in enumerate(dense_results):
        scores[item.id] = scores.get(item.id, 0.0) + dense_weight / (k + rank + 1)
    for rank, item in enumerate(bm25_results):
        scores[item.id] = scores.get(item.id, 0.0) + bm25_weight / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


class LocalVectorStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None
        self._snapshot: _BM25Snapshot | None = None
        self._lock = threading.Lock()

    # ── ChromaDB helpers (no lock needed, PersistentClient is thread-safe) ──

    def _get_client(self):
        if self._client is None:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            self.settings.vector_db_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self.settings.vector_db_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._client

    def _get_collection(self):
        client = self._get_client()
        return client.get_or_create_collection(
            name=self.settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Snapshot management ──

    def _get_snapshot(self) -> _BM25Snapshot:
        """Return the current snapshot, building it lazily if needed."""
        with self._lock:
            if self._snapshot is not None:
                return self._snapshot
        # Build outside the lock (heavy: ChromaDB read + jieba + BM25)
        snapshot = self._build_full_snapshot()
        with self._lock:
            # Another thread may have built it first — keep whichever won
            if self._snapshot is None:
                self._snapshot = snapshot
            return self._snapshot

    def _build_full_snapshot(self) -> _BM25Snapshot:
        t0 = perf_counter()
        collection = self._get_collection()
        results = collection.get(include=["documents", "metadatas"])
        corpus_ids = results["ids"]
        corpus_texts = results["documents"] or []
        metadatas = results.get("metadatas") or []
        logger.info("Loaded %d docs from ChromaDB (%.2fs)", len(corpus_ids), perf_counter() - t0)

        snapshot = _build_bm25_snapshot(corpus_ids, corpus_texts, metadatas)
        logger.info(
            "BM25 snapshot built: %d documents, %d videos",
            len(snapshot.corpus_ids),
            len(snapshot.bvid_chunks),
        )
        return snapshot

    def _swap_snapshot(self, snapshot: _BM25Snapshot) -> None:
        """Atomically replace the live snapshot."""
        with self._lock:
            self._snapshot = snapshot

    # ── Write operations ──

    def replace_video_chunks(
        self,
        *,
        folder_id: int,
        bvid: str,
        video_title: str,
        up_name: str | None,
        transcript_source: str | None,
        manual_tags: list[str],
        chunks: list[dict[str, Any]],
    ) -> None:
        collection = self._get_collection()

        # 1. Snapshot current state under lock (fast)
        with self._lock:
            snap = self._snapshot
            existing_ids = list(snap.bvid_chunks.get(bvid, ())) if snap else []

        # 2. ChromaDB write (no lock, PersistentClient is thread-safe)
        if existing_ids:
            collection.delete(ids=existing_ids)

        if not chunks:
            self._swap_snapshot(self._build_full_snapshot())
            return

        manual_tags_text = ", ".join(manual_tags)
        ids: list[str] = []
        documents: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, Any]] = []

        for chunk in chunks:
            chunk_id = chunk["chunk_id"]
            content = chunk["content"][:8192]
            ids.append(chunk_id)
            documents.append(content)
            embeddings.append(chunk["embedding"])
            metadatas.append(
                {
                    "bvid": bvid,
                    "folder_id": int(folder_id),
                    "video_title": video_title[:512],
                    "up_name": (up_name or "")[:255],
                    "start_seconds": float(chunk["start_seconds"]),
                    "end_seconds": float(chunk["end_seconds"]),
                    "subtitle_source": (transcript_source or "unknown")[:64],
                    "manual_tags": manual_tags_text[:512],
                }
            )

        collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        # 3. Build new snapshot outside lock (heavy: jieba + BM25)
        new_corpus_ids = list(snap.corpus_ids if snap else [])
        new_corpus_texts = list(snap.corpus_texts if snap else [])
        remove_set = set(existing_ids)
        if remove_set:
            paired = [
                (cid, txt)
                for cid, txt in zip(new_corpus_ids, new_corpus_texts)
                if cid not in remove_set
            ]
            new_corpus_ids = [cid for cid, _ in paired]
            new_corpus_texts = [txt for _, txt in paired]
        new_corpus_ids.extend(ids)
        new_corpus_texts.extend(documents)

        new_bvid_chunks = dict(snap.bvid_chunks) if snap else {}
        new_bvid_chunks[bvid] = tuple(ids)

        from rank_bm25 import BM25Okapi

        tokenized_corpus = [_tokenize(t) for t in new_corpus_texts]
        new_snapshot = _BM25Snapshot(
            corpus_ids=tuple(new_corpus_ids),
            corpus_texts=tuple(new_corpus_texts),
            bvid_chunks=new_bvid_chunks,
            bm25=BM25Okapi(tokenized_corpus) if tokenized_corpus else None,
        )
        self._swap_snapshot(new_snapshot)
        logger.info(
            "Replaced chunks for %s: %d chunks, BM25 index updated",
            bvid,
            len(chunks),
        )

    def delete_video_chunks(self, bvid: str) -> None:
        collection = self._get_collection()

        with self._lock:
            snap = self._snapshot
            existing_ids = list(snap.bvid_chunks.get(bvid, ())) if snap else []

        if existing_ids:
            collection.delete(ids=existing_ids)
            self._swap_snapshot(self._build_full_snapshot())

    def reset_collection(self) -> None:
        client = self._get_client()
        try:
            client.delete_collection(self.settings.chroma_collection)
        except Exception:
            pass
        with self._lock:
            self._snapshot = None
        self._get_collection()

    # ── Search (read-only, zero contention) ──

    def _dense_search(
        self,
        collection,
        query_embedding: list[float],
        where_filter: dict[str, Any] | None,
        limit: int,
    ) -> list[_SearchResult]:
        """Vector similarity search via ChromaDB."""
        dense_kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": limit,
            "include": ["metadatas", "documents", "distances"],
        }
        if where_filter:
            dense_kwargs["where"] = where_filter

        try:
            dense_results = collection.query(**dense_kwargs)
        except Exception:
            logger.warning("Dense search failed", exc_info=True)
            return []

        dense_ids = dense_results["ids"][0] if dense_results["ids"] else []
        dense_distances = dense_results["distances"][0] if dense_results["distances"] else []
        return [
            _SearchResult(id=chunk_id, score=1.0 - dist)
            for chunk_id, dist in zip(dense_ids, dense_distances)
        ]

    def _bm25_search(
        self,
        collection,
        snap: _BM25Snapshot,
        query_text: str,
        where_filter: dict[str, Any] | None,
        folder_id: int | None,
        bvid: str | None,
        limit: int,
    ) -> list[_SearchResult]:
        """Keyword search via BM25 using the snapshot."""
        if snap.bm25 is None or not snap.corpus_ids:
            return []

        corpus_ids_list = list(snap.corpus_ids)
        tokenized_query = _tokenize(query_text)
        scores = snap.bm25.get_scores(tokenized_query)

        candidates: list[_SearchResult] = []
        scored_ids: list[str] = []
        for idx, score in enumerate(scores):
            if score > 0 and idx < len(corpus_ids_list):
                candidates.append(_SearchResult(id=corpus_ids_list[idx], score=float(score)))
                scored_ids.append(corpus_ids_list[idx])

        candidates.sort(key=lambda x: x.score, reverse=True)
        hits = candidates[:limit]

        # Batch fetch metadata for filtering
        if where_filter and scored_ids:
            batch_result = collection.get(ids=scored_ids, include=["metadatas"])
            batch_metas = batch_result.get("metadatas") or []
            batch_ids = batch_result.get("ids") or []
            meta_map: dict[str, dict[str, Any]] = {}
            for bid, meta in zip(batch_ids, batch_metas):
                if meta:
                    meta_map[bid] = meta

            hits = [
                hit
                for hit in hits
                if hit.id in meta_map
                and (folder_id is None or meta_map[hit.id].get("folder_id") == folder_id)
                and (not bvid or meta_map[hit.id].get("bvid") == bvid)
            ]

        return hits

    def hybrid_search(
        self,
        *,
        query_embedding: list[float],
        query_text: str,
        folder_id: int | None = None,
        bvid: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        snap = self._get_snapshot()
        collection = self._get_collection()

        where_conditions: list[dict[str, Any]] = []
        if folder_id is not None:
            where_conditions.append({"folder_id": folder_id})
        if bvid:
            where_conditions.append({"bvid": bvid})
        where_filter: dict[str, Any] | None = None
        if len(where_conditions) == 1:
            where_filter = where_conditions[0]
        elif len(where_conditions) > 1:
            where_filter = {"$and": where_conditions}

        # Run dense and BM25 searches in parallel
        with ThreadPoolExecutor(max_workers=2) as pool:
            dense_future = pool.submit(
                self._dense_search, collection, query_embedding, where_filter, limit
            )
            bm25_future = pool.submit(
                self._bm25_search, collection, snap, query_text,
                where_filter, folder_id, bvid, limit,
            )
            dense_hits = dense_future.result()
            bm25_hits = bm25_future.result()

        # RRF fusion
        merged = rrf_merge(dense_hits, bm25_hits)[:limit]
        if not merged:
            return []

        # Fetch full metadata for merged results
        merged_ids = [item[0] for item in merged]
        merged_scores = {item[0]: item[1] for item in merged}
        full_results = collection.get(ids=merged_ids, include=["metadatas", "documents"])

        hits: list[dict[str, Any]] = []
        metas = full_results.get("metadatas") or []
        docs = full_results.get("documents") or []
        ret_ids = full_results.get("ids") or []

        for chunk_id, meta, doc in zip(ret_ids, metas, docs):
            if not meta:
                continue
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "bvid": meta.get("bvid"),
                    "folder_id": meta.get("folder_id"),
                    "video_title": meta.get("video_title"),
                    "up_name": meta.get("up_name"),
                    "start_seconds": meta.get("start_seconds"),
                    "end_seconds": meta.get("end_seconds"),
                    "content": doc or "",
                    "transcript_source": meta.get("subtitle_source"),
                    "manual_tags": meta.get("manual_tags"),
                    "score": merged_scores.get(chunk_id, 0.0),
                }
            )

        hits.sort(key=lambda x: x["score"], reverse=True)
        return hits

    def close(self) -> None:
        self._client = None
        with self._lock:
            self._snapshot = None

    async def ahybrid_search(self, **kwargs) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.hybrid_search, **kwargs)

    async def areplace_video_chunks(self, **kwargs) -> None:
        return await asyncio.to_thread(self.replace_video_chunks, **kwargs)

    async def adelete_video_chunks(self, bvid: str) -> None:
        return await asyncio.to_thread(self.delete_video_chunks, bvid)

    async def areset_collection(self) -> None:
        return await asyncio.to_thread(self.reset_collection)
