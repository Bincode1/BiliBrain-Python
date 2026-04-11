import asyncio
from types import SimpleNamespace

from bilibrain.services.summary import compute_transcript_hash, ensure_video_summary


class _FakeSummaryDb:
    def __init__(self, *, transcript_text: str, existing_summary=None):
        self.video = {"bvid": "BV1test", "title": "测试视频"}
        self.transcript = {
            "bvid": "BV1test",
            "transcript_text": transcript_text,
            "segments": [
                {"start_seconds": index * 10.0, "end_seconds": index * 10.0 + 9.0, "content": chunk}
                for index, chunk in enumerate([text for text in transcript_text.split("\n") if text], start=0)
            ],
        }
        self.summary = existing_summary

    def get_transcript(self, bvid):
        return self.transcript

    def get_video(self, bvid):
        return self.video

    def get_video_summary(self, bvid):
        return self.summary

    def save_video_summary(self, *, bvid, transcript_hash, summary_text):
        self.summary = {
            "bvid": bvid,
            "transcript_hash": transcript_hash,
            "summary_text": summary_text,
            "video_title": self.video["title"],
            "updated_at": "2026-03-24 21:00:00",
        }


class _FakeQwen:
    def __init__(self):
        self.direct_calls = 0
        self.window_calls = 0
        self.reduce_calls = 0

    def ensure_configured(self):
        return None

    async def summarize_video(self, *, video_title, transcript_text):
        self.direct_calls += 1
        return "direct-summary"

    async def summarize_video_window(self, *, video_title, transcript_text):
        self.window_calls += 1
        return f"window-{self.window_calls}"

    async def reduce_video_summaries(self, *, video_title, window_summaries):
        self.reduce_calls += 1
        return "reduced-summary"


def _build_runtime(transcript_text: str, *, existing_summary=None):
    return SimpleNamespace(
        settings=SimpleNamespace(
            transcript_merge_max_gap=2.0,
            transcript_merge_max_duration=120.0,
            transcript_chunk_target_chars=220,
            transcript_chunk_min_chars=80,
            transcript_chunk_overlap_chars=50,
            transcript_chunk_max_tokens=600,
        ),
        db=_FakeSummaryDb(transcript_text=transcript_text, existing_summary=existing_summary),
        qwen=_FakeQwen(),
    )


def test_summary_graph_returns_cached_summary_without_llm_calls():
    transcript_text = "第一段。\n第二段。"
    transcript_hash = compute_transcript_hash(transcript_text)
    runtime = _build_runtime(
        transcript_text,
        existing_summary={
            "bvid": "BV1test",
            "transcript_hash": transcript_hash,
            "summary_text": "cached-summary",
        },
    )

    result = asyncio.run(ensure_video_summary(runtime, "BV1test"))

    assert result["summary_text"] == "cached-summary"
    assert runtime.qwen.direct_calls == 0
    assert runtime.qwen.window_calls == 0
    assert runtime.qwen.reduce_calls == 0


def test_summary_graph_uses_direct_path_for_short_transcript():
    runtime = _build_runtime("第一段。\n第二段。")

    result = asyncio.run(ensure_video_summary(runtime, "BV1test"))

    assert result["summary_text"] == "direct-summary"
    assert runtime.qwen.direct_calls == 1
    assert runtime.qwen.window_calls == 0
    assert runtime.qwen.reduce_calls == 0


def test_summary_graph_uses_windowed_reduce_for_long_transcript():
    transcript_text = "\n".join(["这是一段很长的转写内容" * 150 for _ in range(8)])
    runtime = _build_runtime(transcript_text)

    result = asyncio.run(ensure_video_summary(runtime, "BV1test"))

    assert result["summary_text"] == "reduced-summary"
    assert runtime.qwen.direct_calls == 0
    assert runtime.qwen.window_calls > 1
    assert runtime.qwen.reduce_calls == 1
