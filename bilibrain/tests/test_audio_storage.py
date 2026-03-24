import asyncio
from pathlib import Path
from types import SimpleNamespace

from bilibrain.services.common import default_pipeline_state
from bilibrain.services.pipeline import build_status_payload
from bilibrain.storage import create_audio_storage_service


def test_local_audio_storage_upload_download_and_delete(tmp_path: Path):
    source_path = tmp_path / "source.m4a"
    source_path.write_bytes(b"audio-bytes")

    settings = SimpleNamespace(
        audio_storage_provider="local",
        audio_cache_dir=tmp_path / "storage",
        audio_storage_bucket="bilibrain-audio",
        audio_storage_prefix="audio",
        audio_storage_endpoint="",
        audio_storage_region="us-east-1",
        audio_storage_access_key="",
        audio_storage_secret_key="",
        audio_storage_public_base_url="",
        audio_storage_presign_seconds=3600,
        audio_storage_force_path_style=True,
    )
    storage = create_audio_storage_service(settings)

    async def scenario():
        ref = await storage.upload_audio(source_path, bvid="BV1test")
        assert ref.provider == "local"
        assert ref.object_key == "BV1test.m4a"
        assert ref.url == "/storage/audio/BV1test.m4a"

        downloaded_path = tmp_path / "downloaded.m4a"
        await storage.download_audio(ref.provider, ref.object_key, downloaded_path)
        assert downloaded_path.read_bytes() == b"audio-bytes"

        await storage.delete_audio(ref.provider, ref.object_key)
        assert not (settings.audio_cache_dir / ref.object_key).exists()

    asyncio.run(scenario())


def test_build_status_payload_exposes_audio_url():
    pipeline_state = default_pipeline_state()
    runtime = SimpleNamespace()
    runtime.settings = SimpleNamespace(audio_cache_dir=Path("D:/does-not-matter"))
    runtime.audio_storage = SimpleNamespace(get_audio_url=lambda provider, object_key: f"/storage/audio/{object_key}" if provider and object_key else None)
    runtime.video_tasks = {}
    runtime.db = SimpleNamespace(
        get_video=lambda bvid: {
            "bvid": bvid,
            "title": "测试视频",
            "duration": 120,
            "manual_tags": [],
            "audio_storage_provider": "local",
            "audio_object_key": "BV1test.m4a",
        },
        get_transcript=lambda bvid: None,
        get_pipeline_state=lambda bvid: pipeline_state,
        get_processing_settings=lambda: {"max_video_minutes": 30},
    )

    payload = build_status_payload(runtime, "BV1test")

    assert payload["audio_storage_provider"] == "local"
    assert payload["audio_object_key"] == "BV1test.m4a"
    assert payload["audio_url"] == "/storage/audio/BV1test.m4a"
