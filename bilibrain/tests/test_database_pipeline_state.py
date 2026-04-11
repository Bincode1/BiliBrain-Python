import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from bilibrain.db.database import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    settings = type("Settings", (), {
        "db_path": tmp_path / "test.db",
        "data_dir": tmp_path,
    })()
    return Database(settings)


@pytest.mark.asyncio
async def test_get_pipeline_state_returns_default_when_no_video(db: Database):
    await db.ensure_ready()
    state = await db.get_pipeline_state("BVnotexist")
    assert state["audio"]["status"] == "pending"
    assert state["transcript"]["status"] == "pending"
    assert state["index"]["status"] == "pending"


@pytest.mark.asyncio
async def test_get_pipeline_state_hydrates_audio_from_video_record(db: Database):
    await db.ensure_ready()
    bvid = "BV1test"

    await db.upsert_video({
        "bvid": bvid,
        "folder_id": 1,
        "title": "测试视频",
        "up_name": "test_up",
        "duration": 120,
        "audio_storage_provider": "local",
        "audio_object_key": "BV1test.m4a",
        "audio_uploaded_at": datetime(2026, 3, 27, 12, 0, 0),
    })

    state = await db.get_pipeline_state(bvid)
    assert state["audio"]["status"] == "done"
    assert state["audio"]["object_key"] == "BV1test.m4a"
