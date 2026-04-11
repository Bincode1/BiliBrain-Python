import asyncio
from types import SimpleNamespace

from bilibrain.core.runtime import startup_runtime, shutdown_runtime
from bilibrain.services.ingestion_dispatcher import process_ingestion_task, run_ingestion_dispatcher


class _FakeDb:
    def __init__(self):
        self.ready = False

    def ensure_ready(self):
        self.ready = True


async def _fake_dispatcher(runtime, *, worker_id, poll_interval, max_concurrency, stale_after_seconds):
    runtime._dispatcher_started = {
        "worker_id": worker_id,
        "poll_interval": poll_interval,
        "max_concurrency": max_concurrency,
        "stale_after_seconds": stale_after_seconds,
    }
    await asyncio.sleep(3600)


class _Closable:
    async def close(self):
        return None


class _VectorClosable:
    def close(self):
        return None


def test_startup_runtime_starts_ingestion_dispatcher(monkeypatch):
    runtime = SimpleNamespace(
        settings=SimpleNamespace(
            audio_cache_dir=SimpleNamespace(mkdir=lambda parents, exist_ok: None),
            tools_workspace_root=SimpleNamespace(mkdir=lambda parents, exist_ok: None),
            skills_builtin_root=SimpleNamespace(mkdir=lambda parents, exist_ok: None),
            skills_user_root=SimpleNamespace(mkdir=lambda parents, exist_ok: None),
            skills_repo_root=SimpleNamespace(mkdir=lambda parents, exist_ok: None),
            ingestion_poll_interval_seconds=1.5,
            ingestion_max_concurrency=2,
            reset_max_concurrency=3,
            ingestion_task_stale_after_seconds=1200,
        ),
        db=_FakeDb(),
        bili=_Closable(),
        embedder=_Closable(),
        qwen=_Closable(),
        asr=_Closable(),
        vector_store=_VectorClosable(),
        video_tasks={},
        reset_tasks={},
        reset_statuses={},
        cache_tasks={},
        ingestion_dispatcher_task=None,
        ingestion_worker_id=None,
        reset_limiter=None,
    )

    monkeypatch.setattr("bilibrain.core.runtime.run_ingestion_dispatcher", _fake_dispatcher)
    monkeypatch.setattr("bilibrain.core.runtime.build_worker_id", lambda prefix: f"{prefix}-test-worker")
    monkeypatch.setattr("bilibrain.core.runtime.create_tool_service", lambda settings, db: object())
    monkeypatch.setattr("bilibrain.core.runtime.create_skill_service", lambda settings: object())
    async def scenario():
        await startup_runtime(runtime)
        await asyncio.sleep(0)
        assert runtime.db.ready is True
        assert runtime.ingestion_worker_id == "app-test-worker"
        assert runtime._dispatcher_started["max_concurrency"] == 2
        assert runtime.ingestion_dispatcher_task is not None
        assert runtime.reset_limiter is not None
        await shutdown_runtime(runtime)

    asyncio.run(scenario())


def test_process_ingestion_task_sends_heartbeat_and_marks_success(monkeypatch):
    touched = []
    succeeded = []

    class _FakeDb:
        def touch_ingestion_task_lock(self, task_id, *, worker_id=None):
            touched.append((task_id, worker_id))
            return {"task_id": task_id}

        def mark_ingestion_task_succeeded(self, task_id):
            succeeded.append(task_id)
            return {"task_id": task_id}

        def mark_ingestion_task_failed(self, task_id, error):
            raise AssertionError(f"unexpected failure: {error}")

    async def _fake_graph(runtime, bvid):
        await asyncio.sleep(1.1)

    runtime = SimpleNamespace(db=_FakeDb())
    monkeypatch.setattr("bilibrain.services.ingestion_dispatcher.run_ingestion_graph", _fake_graph)

    asyncio.run(
        process_ingestion_task(
            runtime,
            {"task_id": 5, "bvid": "BV1"},
            worker_id="worker-1",
            stale_after_seconds=1,
        )
    )

    assert touched
    assert succeeded == [5]


def test_run_ingestion_dispatcher_marks_stale_tasks_before_polling(monkeypatch):
    class _FakeDb:
        def __init__(self):
            self.stale_calls = []

        def mark_stale_ingestion_tasks(self, *, stale_after_seconds, limit):
            self.stale_calls.append((stale_after_seconds, limit))
            return []

        def claim_next_ingestion_task(self, *, worker_id, stale_after_seconds):
            return None

    runtime = SimpleNamespace(
        db=_FakeDb(),
        video_tasks={},
    )

    async def scenario():
        task = asyncio.create_task(
            run_ingestion_dispatcher(
                runtime,
                worker_id="worker-1",
                poll_interval=0.2,
                max_concurrency=1,
                stale_after_seconds=120,
            )
        )
        await asyncio.sleep(0.25)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())

    assert runtime.db.stale_calls
