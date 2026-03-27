from __future__ import annotations

from typing import Any

from pymilvus import (
    AnnSearchRequest,
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    Function,
    FunctionType,
    WeightedRanker,
    connections,
    utility,
)

from bilibrain.core.config import Settings


class MilvusStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.alias = "bilibrain"
        self._connected = False

    def _connect(self) -> None:
        if self._connected:
            return
        kwargs: dict[str, Any] = {
            "alias": self.alias,
            "host": self.settings.milvus_host,
            "port": self.settings.milvus_port,
            "db_name": self.settings.milvus_database,
        }
        if self.settings.milvus_user:
            kwargs["user"] = self.settings.milvus_user
        if self.settings.milvus_password:
            kwargs["password"] = self.settings.milvus_password
        connections.connect(**kwargs)
        self._connected = True

    def _collection(self) -> Collection:
        self._connect()
        if utility.has_collection(self.settings.milvus_collection, using=self.alias):
            collection = Collection(self.settings.milvus_collection, using=self.alias)
            field_names = {field.name for field in collection.schema.fields}
            content_field = next((field for field in collection.schema.fields if field.name == "content"), None)
            content_params = getattr(content_field, "params", {}) if content_field is not None else {}
            if (
                "manual_tags" not in field_names
                or "content_sparse" not in field_names
                or not bool(content_params.get("enable_analyzer"))
            ):
                utility.drop_collection(self.settings.milvus_collection, using=self.alias)
                self._create_collection()
        else:
            self._create_collection()
        return Collection(self.settings.milvus_collection, using=self.alias)

    def _create_collection(self) -> None:
        fields = [
            FieldSchema("chunk_id", DataType.VARCHAR, is_primary=True, auto_id=False, max_length=128),
            FieldSchema("bvid", DataType.VARCHAR, max_length=32),
            FieldSchema("folder_id", DataType.INT64),
            FieldSchema("video_title", DataType.VARCHAR, max_length=512),
            FieldSchema("up_name", DataType.VARCHAR, max_length=255),
            FieldSchema("start_seconds", DataType.DOUBLE),
            FieldSchema("end_seconds", DataType.DOUBLE),
            FieldSchema("content", DataType.VARCHAR, max_length=8192, enable_analyzer=True),
            FieldSchema("content_sparse", DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema("subtitle_source", DataType.VARCHAR, max_length=64),
            FieldSchema("manual_tags", DataType.VARCHAR, max_length=512),
            FieldSchema(
                "embedding",
                DataType.FLOAT_VECTOR,
                dim=self.settings.milvus_dimension,
            ),
        ]
        bm25_function = Function(
            name="content_bm25_emb",
            function_type=FunctionType.BM25,
            input_field_names=["content"],
            output_field_names=["content_sparse"],
        )
        schema = CollectionSchema(
            fields,
            description="BiliBrain transcript chunks in Milvus",
            functions=[bm25_function],
        )
        collection = Collection(self.settings.milvus_collection, schema=schema, using=self.alias)
        collection.create_index(
            "embedding",
            {
                "index_type": "HNSW",
                "metric_type": "COSINE",
                "params": {"M": 16, "efConstruction": 200},
            },
        )
        collection.create_index(
            "content_sparse",
            {
                "index_type": "SPARSE_INVERTED_INDEX",
                "metric_type": "BM25",
                "params": {
                    "inverted_index_algo": "DAAT_MAXSCORE",
                    "bm25_k1": 1.2,
                    "bm25_b": 0.75,
                },
            },
        )
        collection.load()
        self._collection_loaded = True

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
        collection = self._collection()
        safe_bvid = bvid.replace("\\", "\\\\").replace('"', '\\"')
        collection.delete(expr=f'bvid == "{safe_bvid}"')
        collection.flush()
        payload = []
        manual_tags_text = ", ".join(manual_tags)
        for chunk in chunks:
            payload.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "bvid": bvid,
                    "folder_id": int(folder_id),
                    "video_title": video_title[:512],
                    "up_name": (up_name or "")[:255],
                    "start_seconds": float(chunk["start_seconds"]),
                    "end_seconds": float(chunk["end_seconds"]),
                    "content": chunk["content"][:8192],
                    "subtitle_source": (transcript_source or "unknown")[:64],
                    "manual_tags": manual_tags_text[:512],
                    "embedding": chunk["embedding"],
                }
            )
        if payload:
            collection.insert(payload)
            collection.flush()

    def delete_video_chunks(self, bvid: str) -> None:
        self._connect()
        if not utility.has_collection(self.settings.milvus_collection, using=self.alias):
            return
        collection = Collection(self.settings.milvus_collection, using=self.alias)
        safe_bvid = bvid.replace("\\", "\\\\").replace('"', '\\"')
        collection.delete(expr=f'bvid == "{safe_bvid}"')
        collection.flush()

    def reset_collection(self) -> None:
        self._connect()
        if utility.has_collection(self.settings.milvus_collection, using=self.alias):
            utility.drop_collection(self.settings.milvus_collection, using=self.alias)
        self._create_collection()

    def hybrid_search(
        self,
        *,
        query_embedding: list[float],
        query_text: str,
        folder_id: int | None = None,
        bvid: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        self._connect()
        if not utility.has_collection(self.settings.milvus_collection, using=self.alias):
            return []
        collection = Collection(self.settings.milvus_collection, using=self.alias)
        expr_parts: list[str] = []
        if folder_id is not None:
            expr_parts.append(f"folder_id == {int(folder_id)}")
        if bvid:
            safe_bvid = str(bvid).replace("\\", "\\\\").replace('"', '\\"')
            expr_parts.append(f'bvid == "{safe_bvid}"')
        expr = " and ".join(expr_parts) if expr_parts else None
        dense_request = AnnSearchRequest(
            data=[query_embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=limit,
            expr=expr,
        )
        sparse_request = AnnSearchRequest(
            data=[query_text],
            anns_field="content_sparse",
            param={},
            limit=limit,
            expr=expr,
        )
        results = collection.hybrid_search(
            reqs=[dense_request, sparse_request],
            rerank=WeightedRanker(0.65, 0.35),
            limit=limit,
            output_fields=[
                "bvid",
                "folder_id",
                "video_title",
                "up_name",
                "start_seconds",
                "end_seconds",
                "content",
                "subtitle_source",
                "manual_tags",
            ],
        )
        hits: list[dict[str, Any]] = []
        for hit in results[0]:
            entity = hit.entity
            hits.append(
                {
                    "chunk_id": hit.id,
                    "bvid": entity.get("bvid"),
                    "folder_id": entity.get("folder_id"),
                    "video_title": entity.get("video_title"),
                    "up_name": entity.get("up_name"),
                    "start_seconds": entity.get("start_seconds"),
                    "end_seconds": entity.get("end_seconds"),
                    "content": entity.get("content"),
                    "transcript_source": entity.get("subtitle_source"),
                    "manual_tags": entity.get("manual_tags"),
                    "score": float(hit.score),
                }
            )
        return hits

    def close(self) -> None:
        if self._connected:
            connections.disconnect(self.alias)
            self._connected = False
