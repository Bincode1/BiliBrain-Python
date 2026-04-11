import asyncio
from types import SimpleNamespace

from bilibrain.services.pipeline import _execute_reset_video_processing, reset_all_video_processing, reset_video_processing


class _FakeVectorStore:
    def __init__(self):
        self.deleted_bvid = None

    def delete_video_chunks(self, bvid):
        self.deleted_bvid = bvid


class _FakeAudioStorage:
    def get_audio_url(self, provider, object_key):
        return f"{provider}://{object_key}"


class _FakeResetDb:
    def __init__(self):
        self.deleted_task_bvid = None
        self.cancelled_task_ids = []

    def get_video(self, bvid):
        return {
            "bvid": bvid,
            "title": "demo",
            "audio_storage_provider": "local",
            "audio_object_key": f"{bvid}.m4a",
        }

    def get_active_ingestion_task_for_bvid(self, bvid):
        return None

    def get_transcript(self, bvid):
        return None

    def get_video_summary(self, bvid):
        return None

    def get_pipeline_state(self, bvid):
        return {
            "audio": {"status": "done", "count": 0},
            "transcript": {"status": "pending", "segment_count": 0},
            "index": {"status": "pending", "count": 0},
        }

    def get_processing_settings(self):
        return {"max_video_minutes": 30}

    def reset_video_processing_artifacts(self, bvid):
        self.deleted_task_bvid = bvid
        return None

    def list_ingestion_tasks(self, statuses=None, limit=5000):
        return [{"task_id": 7}]

    def cancel_ingestion_task(self, task_id):
        self.cancelled_task_ids.append(task_id)
        return True

    def list_all_video_bvids(self):
        return ["BV1", "BV2"]

    def delete_all_transcripts(self):
        return 2

    def delete_all_video_summaries(self):
        return 1

    def reset_all_pipeline_states(self):
        return 2

    def clear_all_video_processing_markers(self):
        return 2

    def delete_all_ingestion_tasks(self):
        return 3


def test_reset_video_processing_enqueues_background_task(monkeypatch):
    runtime = SimpleNamespace(
        db=_FakeResetDb(),
        audio_storage=_FakeAudioStorage(),
        vector_store=_FakeVectorStore(),
        video_tasks={},
        reset_tasks={},
        reset_statuses={},
        reset_limiter=asyncio.Semaphore(1),
        settings=SimpleNamespace(reset_max_concurrency=1),
    )

    finished = asyncio.Event()

    async def _fake_execute(runtime, bvid):
        runtime.reset_statuses[bvid] = {"status": "running", "error": None}
        await finished.wait()
        runtime.reset_statuses.pop(bvid, None)
        runtime.reset_tasks.pop(bvid, None)

    monkeypatch.setattr(
        "bilibrain.services.pipeline._execute_reset_video_processing",
        _fake_execute,
    )

    async def scenario():
        first = await reset_video_processing(runtime, "BV1")
        second = await reset_video_processing(runtime, "BV1")
        assert first["reset"] is True
        assert first["started"] is True
        assert first["running"] is True
        assert first["operation"] == "reset"
        assert second["started"] is False
        assert runtime.reset_statuses["BV1"]["status"] == "running"
        finished.set()
        await asyncio.gather(*runtime.reset_tasks.values(), return_exceptions=True)

    asyncio.run(scenario())

    assert "BV1" not in runtime.reset_tasks
    assert "BV1" not in runtime.reset_statuses


def test_execute_reset_video_processing_deletes_task_history():
    runtime = SimpleNamespace(
        db=_FakeResetDb(),
        audio_storage=_FakeAudioStorage(),
        vector_store=_FakeVectorStore(),
        video_tasks={},
        reset_tasks={},
        reset_statuses={},
        reset_limiter=asyncio.Semaphore(1),
        settings=SimpleNamespace(reset_max_concurrency=1),
    )

    asyncio.run(_execute_reset_video_processing(runtime, "BV1"))

    assert runtime.db.deleted_task_bvid == "BV1"
    assert runtime.vector_store.deleted_bvid == "BV1"
    assert runtime.reset_statuses == {}


def test_reset_all_video_processing_keeps_audio_cache():
    vector_store = SimpleNamespace(reset_collection=lambda: None)
    runtime = SimpleNamespace(
        db=_FakeResetDb(),
        audio_storage=_FakeAudioStorage(),
        vector_store=vector_store,
        video_tasks={},
        reset_tasks={},
        reset_statuses={},
        settings=SimpleNamespace(reset_max_concurrency=1),
    )

    payload = asyncio.run(reset_all_video_processing(runtime))

    assert payload["reset"] is True
    assert payload["video_count"] == 2
    assert payload["transcript_count"] == 2
    assert payload["summary_count"] == 1
    assert payload["task_count"] == 3
    assert "audio_file_count" not in payload
    assert runtime.db.cancelled_task_ids == [7]
