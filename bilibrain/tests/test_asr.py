import asyncio
from pathlib import Path
from types import SimpleNamespace

from bilibrain.ai.asr import WhisperAsrClient


def _build_client(*, chunk_concurrency: int = 2) -> WhisperAsrClient:
    client = object.__new__(WhisperAsrClient)
    client.settings = SimpleNamespace(
        whisper_model="tiny",
        whisper_device="cpu",
        whisper_compute_type="int8",
        asr_language="zh",
        asr_chunk_seconds=120,
        asr_target_chunk_seconds=90,
        asr_chunk_overlap_seconds=1.0,
        asr_chunk_concurrency=chunk_concurrency,
        asr_silence_min_seconds=0.6,
        asr_silence_noise_db=-35.0,
    )
    client._model = None
    return client


def test_transcribe_audio_file_limits_chunk_concurrency_and_preserves_order(monkeypatch, tmp_path: Path):
    client = _build_client(chunk_concurrency=2)
    source_path = tmp_path / "source.mp3"
    source_path.write_bytes(b"audio")

    active_calls = 0
    max_active_calls = 0
    progress_events = []

    def _fake_chunk_audio(self, audio_path: Path, output_dir: Path):
        return [
            {
                "path": output_dir / "chunk-000.mp3",
                "start_seconds": 0.0,
                "end_seconds": 5.0,
                "clip_start_seconds": 0.0,
                "clip_end_seconds": 5.0,
            },
            {
                "path": output_dir / "chunk-001.mp3",
                "start_seconds": 5.0,
                "end_seconds": 10.0,
                "clip_start_seconds": 4.0,
                "clip_end_seconds": 10.0,
            },
            {
                "path": output_dir / "chunk-002.mp3",
                "start_seconds": 10.0,
                "end_seconds": 15.0,
                "clip_start_seconds": 10.0,
                "clip_end_seconds": 15.0,
            },
        ]

    def _fake_transcribe_file_sync(self, audio_path: Path) -> str:
        nonlocal active_calls, max_active_calls
        delays = {
            "chunk-000.mp3": 0.05,
            "chunk-001.mp3": 0.01,
            "chunk-002.mp3": 0.03,
        }
        payloads = {
            "chunk-000.mp3": "这是第一段完整内容",
            "chunk-001.mp3": "这是第一段完整内容 第二段内容",
            "chunk-002.mp3": "这是第三段内容",
        }
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        try:
            import time
            time.sleep(delays[audio_path.name])
            return payloads[audio_path.name]
        finally:
            active_calls -= 1

    monkeypatch.setattr(WhisperAsrClient, "_chunk_audio", _fake_chunk_audio)
    monkeypatch.setattr(WhisperAsrClient, "_transcribe_file_sync", _fake_transcribe_file_sync)

    payload = asyncio.run(client.transcribe_audio_file(source_path, on_progress=progress_events.append))

    assert max_active_calls == 2
    assert payload["segment_count"] == 3
    assert [segment["content"] for segment in payload["segments"]] == [
        "这是第一段完整内容",
        "第二段内容",
        "这是第三段内容",
    ]
    assert progress_events[0]["stage"] == "chunking"
    assert progress_events[-1]["completed_chunks"] == 3
    assert progress_events[-1]["message"] == "正在转写音频块 3/3"
