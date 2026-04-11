import asyncio
from types import SimpleNamespace

from bilibrain.services.ingestion_queue import enqueue_video_processing


class _FakeQueueDb:
    def __init__(self):
        self.video_rows = {
            "BV1": {"bvid": "BV1", "is_invalid": False},
            "BV2": {"bvid": "BV2", "is_invalid": False},
        }
        self.active_tasks = {}
        self.created_tasks = []

    def get_video(self, bvid):
        return self.video_rows.get(bvid)

    def get_active_ingestion_task_for_bvid(self, bvid):
        return self.active_tasks.get(bvid)

    def create_ingestion_task(self, *, bvid, batch_id=None, options=None):
        task = {
            "task_id": len(self.created_tasks) + 1,
            "batch_id": batch_id,
            "bvid": bvid,
            "status": "queued",
        }
        self.created_tasks.append(task)
        self.active_tasks[bvid] = task
        return task


def test_enqueue_video_processing_creates_task(monkeypatch):
    runtime = SimpleNamespace(db=_FakeQueueDb())

    monkeypatch.setattr(
        "bilibrain.services.pipeline.build_status_payload",
        lambda runtime, bvid: {"bvid": bvid, "overall_status": "pending", "running": False},
    )

    payload = asyncio.run(enqueue_video_processing(runtime, "BV1"))

    assert payload["started"] is True
    assert payload["task_id"] == 1


def test_enqueue_video_processing_reuses_active_task(monkeypatch):
    db = _FakeQueueDb()
    db.active_tasks["BV1"] = {"task_id": 99, "bvid": "BV1", "status": "queued"}
    runtime = SimpleNamespace(db=db)

    monkeypatch.setattr(
        "bilibrain.services.pipeline.build_status_payload",
        lambda runtime, bvid: {"bvid": bvid, "overall_status": "pending", "running": True},
    )

    payload = asyncio.run(enqueue_video_processing(runtime, "BV1"))

    assert payload["started"] is False
    assert payload["task_id"] == 99


def test_enqueue_video_processing_creates_new_task_after_finished_attempt(monkeypatch):
    db = _FakeQueueDb()
    runtime = SimpleNamespace(db=db)

    monkeypatch.setattr(
        "bilibrain.services.pipeline.build_status_payload",
        lambda runtime, bvid: {"bvid": bvid, "overall_status": "pending", "running": False},
    )

    payload = asyncio.run(enqueue_video_processing(runtime, "BV1"))

    assert payload["started"] is True
    assert payload["task_id"] == 1
    assert len(db.created_tasks) == 1


def test_enqueue_video_processing_serializes_duplicate_requests(monkeypatch):
    runtime = SimpleNamespace(db=_FakeQueueDb())

    monkeypatch.setattr(
        "bilibrain.services.pipeline.build_status_payload",
        lambda runtime, bvid: {
            "bvid": bvid,
            "overall_status": "pending",
            "running": False,
        },
    )

    async def scenario():
        return await asyncio.gather(
            enqueue_video_processing(runtime, "BV1"),
            enqueue_video_processing(runtime, "BV1"),
        )

    first, second = asyncio.run(scenario())

    started_count = sum(1 for item in (first, second) if item["started"])
    assert started_count == 1
    assert len(runtime.db.created_tasks) == 1
