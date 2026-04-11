import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from bilibrain.graphs.ingestion import get_ingestion_graph
from bilibrain.services.common import default_pipeline_state
from bilibrain.services.pipeline import run_video_pipeline


class _FakeDb:
    def __init__(self, *, duration: int = 120):
        self.video = {
            "bvid": "BV1test",
            "folder_id": 10,
            "title": "测试视频",
            "up_name": "UP 主",
            "duration": duration,
            "cid": None,
            "manual_tags": ["agent"],
            "is_invalid": False,
            "audio_storage_provider": None,
            "audio_object_key": None,
            "transcript_source": None,
        }
        self.transcript = None
        self.summary = None
        self.pipeline_state = default_pipeline_state()

    def get_video(self, bvid):
        if bvid != self.video["bvid"]:
            return None
        return self.video

    def get_processing_settings(self):
        return {"max_video_minutes": 30}

    def get_pipeline_state(self, bvid):
        return deepcopy(self.pipeline_state)

    def update_pipeline_step(self, bvid, step, status, error=None, **extra):
        payload = self.pipeline_state[step]
        payload["status"] = status
        payload["error"] = error
        payload.update(extra)
        self.pipeline_state[step] = payload
        return deepcopy(self.pipeline_state)

    def mark_video_processed(
        self,
        *,
        bvid,
        cid=None,
        transcript_source=None,
        audio_storage_provider=None,
        audio_object_key=None,
    ):
        if cid is not None:
            self.video["cid"] = cid
        if transcript_source is not None:
            self.video["transcript_source"] = transcript_source
        if audio_storage_provider is not None:
            self.video["audio_storage_provider"] = audio_storage_provider
        if audio_object_key is not None:
            self.video["audio_object_key"] = audio_object_key

    def get_transcript(self, bvid):
        return self.transcript

    def save_transcript(self, *, bvid, source_model, transcript_text, segments):
        self.transcript = {
            "bvid": bvid,
            "source_model": source_model,
            "transcript_text": transcript_text,
            "segments": segments,
            "segment_count": len(segments),
            "updated_at": "2026-03-24 20:00:00",
        }

    def get_video_summary(self, bvid):
        return self.summary


class _FakeBili:
    async def download_audio_track(self, bvid, output_path: Path):
        output_path.write_bytes(b"audio-bytes")
        return {"cid": 123}


class _FakeAudioStorage:
    async def upload_audio(self, source_path: Path, *, bvid: str):
        return SimpleNamespace(provider="local", object_key=f"{bvid}.m4a", url=f"/storage/audio/{bvid}.m4a")

    async def download_audio(self, provider_name: str, object_key: str, target_path: Path):
        target_path.write_bytes(b"cached-audio")
        return target_path

    async def delete_audio(self, provider_name: str, object_key: str):
        return None

    def get_audio_url(self, provider_name: str | None, object_key: str | None):
        if provider_name and object_key:
            return f"/storage/audio/{object_key}"
        return None


class _FakeAsr:
    def ensure_configured(self):
        return None

    async def transcribe_audio_file(self, audio_path: Path, *, on_progress=None):
        if on_progress:
            await on_progress({"stage": "chunking", "message": "正在分析静音并切分音频"})
            await on_progress({"stage": "transcribing", "message": "正在转写音频块 2/2"})
        return {
            "model": "qwen-asr",
            "text": "LangGraph 用来编排状态化流程。",
            "segment_count": 2,
            "segments": [
                {"start_seconds": 0.0, "end_seconds": 3.0, "content": "LangGraph 用来编排状态化流程。"},
                {"start_seconds": 3.0, "end_seconds": 6.0, "content": "它适合复杂工作流。"},
            ],
        }


class _FakeEmbedder:
    def __init__(self):
        self.calls = []

    def ensure_configured(self):
        return None

    async def embed_texts(self, texts):
        self.calls.append(list(texts))
        return [[0.1, 0.2] for _ in texts]


class _FakeVectorStore:
    def __init__(self):
        self.last_replace = None

    def replace_video_chunks(self, **kwargs):
        self.last_replace = kwargs


def _build_runtime(*, duration: int = 120):
    return SimpleNamespace(
        settings=SimpleNamespace(
            asr_model="qwen-asr",
            asr_chunk_concurrency=2,
            embedding_model="bge-m3",
            transcript_merge_max_gap=2.0,
            transcript_merge_max_duration=120.0,
            transcript_chunk_target_chars=220,
            transcript_chunk_min_chars=80,
            transcript_chunk_overlap_chars=50,
            transcript_chunk_max_tokens=600,
            audio_cache_dir=Path("D:/does-not-matter"),
        ),
        db=_FakeDb(duration=duration),
        bili=_FakeBili(),
        audio_storage=_FakeAudioStorage(),
        asr=_FakeAsr(),
        embedder=_FakeEmbedder(),
        vector_store=_FakeVectorStore(),
    )


def test_get_ingestion_graph_is_cached():
    assert get_ingestion_graph() is get_ingestion_graph()


def test_run_video_pipeline_builds_knowledge_assets(monkeypatch):
    runtime = _build_runtime()
    summary_calls = []

    async def _fake_summary(_runtime, bvid):
        summary_calls.append(bvid)
        return {"bvid": bvid, "summary_text": "摘要"}

    monkeypatch.setattr("bilibrain.graphs.ingestion.nodes.ensure_video_summary", _fake_summary)

    asyncio.run(run_video_pipeline(runtime, "BV1test"))

    assert runtime.db.pipeline_state["audio"]["status"] == "done"
    assert runtime.db.pipeline_state["transcript"]["status"] == "done"
    assert runtime.db.pipeline_state["index"]["status"] == "done"
    assert runtime.db.transcript is not None
    assert runtime.vector_store.last_replace is not None
    assert runtime.vector_store.last_replace["bvid"] == "BV1test"
    assert summary_calls == ["BV1test"]


def test_run_video_pipeline_swallows_summary_failure(monkeypatch):
    runtime = _build_runtime()

    async def _broken_summary(_runtime, _bvid):
        raise RuntimeError("summary failed")

    monkeypatch.setattr("bilibrain.graphs.ingestion.nodes.ensure_video_summary", _broken_summary)

    asyncio.run(run_video_pipeline(runtime, "BV1test"))

    assert runtime.db.pipeline_state["index"]["status"] == "done"
    assert runtime.vector_store.last_replace is not None


def test_run_video_pipeline_marks_validation_failure():
    runtime = _build_runtime(duration=60 * 31)

    with pytest.raises(RuntimeError, match="超过当前 30 分钟限制"):
        asyncio.run(run_video_pipeline(runtime, "BV1test"))

    assert runtime.db.pipeline_state["audio"]["status"] == "failed"
