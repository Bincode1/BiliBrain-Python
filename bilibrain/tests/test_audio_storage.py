import asyncio
from pathlib import Path
from types import SimpleNamespace

from bilibrain.storage import AudioStorageService


def test_local_audio_storage_upload_download_and_delete(tmp_path: Path):
    source_path = tmp_path / "source.m4a"
    source_path.write_bytes(b"audio-bytes")

    settings = SimpleNamespace(
        audio_dir=tmp_path / "storage",
    )
    storage = AudioStorageService(settings)

    async def scenario():
        ref = await storage.upload_audio(source_path, bvid="BV1test")
        assert ref.provider == "local"
        assert ref.object_key == "BV1test.m4a"
        assert ref.url == "/storage/audio/BV1test.m4a"

        downloaded_path = tmp_path / "downloaded.m4a"
        await storage.download_audio(ref.provider, ref.object_key, downloaded_path)
        assert downloaded_path.read_bytes() == b"audio-bytes"

        await storage.delete_audio(ref.provider, ref.object_key)
        assert not (settings.audio_dir / ref.object_key).exists()

    asyncio.run(scenario())


def test_get_audio_url_returns_correct_path():
    settings = SimpleNamespace(audio_dir=Path("/tmp/audio"))
    storage = AudioStorageService(settings)

    assert storage.get_audio_url("BV1test.m4a") == "/storage/audio/BV1test.m4a"
    assert storage.get_audio_url(None) is None
    assert storage.get_audio_url("") is None
