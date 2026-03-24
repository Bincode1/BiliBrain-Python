import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from bilibrain.services.common import (
    default_pipeline_state,
    estimate_text_tokens,
    hybrid_rerank_hits,
    merge_subtitle_segments,
    normalize_topic_tags,
    pipeline_action_label,
    pipeline_overall_status,
    rank_bm25_chunks,
    rank_chunks,
)
from bilibrain.services.catalog import (
    build_folder_videos_payload,
    build_folders_payload,
    folder_list_cache_key,
    folder_videos_cache_key,
)
from bilibrain.services.summary import (
    classify_query_intent,
    pack_summary_documents,
    pack_summary_windows,
)


def test_merge_subtitle_segments_breaks_on_large_gap():
    subtitles = [
        {"from": 0, "to": 1, "content": "LangGraph 是一个"},
        {"from": 1.1, "to": 2.0, "content": "状态机框架"},
        {"from": 5.5, "to": 6.0, "content": "接下来我们看 checkpoint"},
    ]
    result = merge_subtitle_segments(
        subtitles,
        max_gap=2.0,
        max_duration=120.0,
        max_tokens=20,
    )
    assert len(result) == 2
    assert "状态机框架" in result[0]["content"]
    assert "checkpoint" in result[1]["content"]


def test_merge_subtitle_segments_uses_sentence_aware_overlap():
    subtitles = [
        {"from": 0, "to": 2, "content": "LangGraph 的核心是状态图。"},
        {"from": 2, "to": 4, "content": "它把节点执行和状态更新拆开。"},
        {"from": 4, "to": 6, "content": "Checkpoint 用来做持久化和恢复。"},
        {"from": 6, "to": 8, "content": "调试时可以回放每一步状态。"},
    ]
    result = merge_subtitle_segments(
        subtitles,
        max_gap=2.0,
        max_duration=120.0,
        target_chars=36,
        min_chars=18,
        overlap_chars=18,
        max_tokens=30,
    )
    assert len(result) == 3
    assert "它把节点执行和状态更新拆开。" in result[0]["content"]
    assert "它把节点执行和状态更新拆开。" in result[1]["content"]
    assert "Checkpoint 用来做持久化和恢复。" in result[1]["content"]


def test_merge_subtitle_segments_prefers_token_budget_over_small_char_target():
    subtitles = [
        {"from": 0, "to": 2, "content": "第一部分介绍大模型和 Transformer。"},
        {"from": 2, "to": 4, "content": "第二部分介绍 tokenizer 和 token。"},
        {"from": 4, "to": 6, "content": "第三部分介绍 context 和 context window。"},
    ]
    result = merge_subtitle_segments(
        subtitles,
        max_gap=2.0,
        max_duration=120.0,
        target_chars=36,
        min_chars=18,
        overlap_chars=0,
        max_tokens=600,
    )
    assert len(result) == 1
    assert "Transformer" in result[0]["content"]
    assert "context window" in result[0]["content"]


def test_merge_subtitle_segments_can_merge_across_coarse_asr_ranges():
    subtitles = [
        {
            "from": 0,
            "to": 90,
            "content": "第一部分介绍大模型和 Transformer。第二部分介绍 tokenizer 和 token。",
        },
        {
            "from": 90,
            "to": 180,
            "content": "第三部分介绍 context 和 context window。第四部分介绍 prompt 和 tool。",
        },
        {
            "from": 180,
            "to": 270,
            "content": "第五部分介绍 MCP、Agent 和 Agent Skill。",
        },
    ]
    result = merge_subtitle_segments(
        subtitles,
        max_gap=2.0,
        max_duration=480.0,
        target_chars=220,
        min_chars=80,
        overlap_chars=0,
        max_tokens=600,
    )
    assert len(result) == 1
    assert "Transformer" in result[0]["content"]
    assert "Agent Skill" in result[0]["content"]


def test_merge_subtitle_segments_respects_max_token_limit():
    subtitles = [
        {
            "from": 0,
            "to": 6,
            "content": "LangGraph checkpoint persistence state recovery debugging replay tracing observability",
        }
    ]
    result = merge_subtitle_segments(
        subtitles,
        max_gap=2.0,
        max_duration=120.0,
        target_chars=120,
        min_chars=20,
        overlap_chars=0,
        max_tokens=12,
    )
    assert len(result) >= 2
    assert all(estimate_text_tokens(item["content"]) <= 12 for item in result)


def test_rank_chunks_prefers_keyword_and_vector_match():
    chunks = [
        {
            "video_title": "LangGraph 教程",
            "content": "checkpoint 用于恢复图状态",
            "embedding": [1.0, 0.0],
        },
        {
            "video_title": "FastAPI 入门",
            "content": "依赖注入与路由设计",
            "embedding": [0.0, 1.0],
        },
    ]
    result = rank_chunks(
        query="LangGraph checkpoint 是什么",
        query_embedding=[0.9, 0.1],
        chunks=chunks,
        limit=2,
    )
    assert result[0]["video_title"] == "LangGraph 教程"


def test_rank_bm25_chunks_prefers_exact_lexical_hit():
    chunks = [
        {
            "chunk_id": "a",
            "video_title": "Agent 教程",
            "content": "agent skill 用来规定做事步骤和规则",
            "manual_tags": "agent,skill",
        },
        {
            "chunk_id": "b",
            "video_title": "天气工具",
            "content": "tool 用来查询实时天气",
            "manual_tags": "tool,weather",
        },
    ]
    result = rank_bm25_chunks(query="agent skill 是什么", chunks=chunks, limit=2)
    assert result[0]["chunk_id"] == "a"


def test_hybrid_rerank_hits_merges_dense_and_bm25_signals():
    dense_hits = [
        {
            "chunk_id": "a",
            "video_title": "上下文工程",
            "content": "context engineering 关注写入 选择 压缩 隔离",
            "manual_tags": "context",
            "score": 0.82,
        },
        {
            "chunk_id": "b",
            "video_title": "别的主题",
            "content": "这里只提到了 prompt",
            "manual_tags": "prompt",
            "score": 0.79,
        },
    ]
    bm25_hits = [
        {
            "chunk_id": "a",
            "video_title": "上下文工程",
            "content": "context engineering 关注写入 选择 压缩 隔离",
            "manual_tags": "context",
            "bm25_score": 3.2,
        },
        {
            "chunk_id": "c",
            "video_title": "记忆系统",
            "content": "写入上下文和 memory retrieval",
            "manual_tags": "memory,context",
            "bm25_score": 2.4,
        },
    ]
    result = hybrid_rerank_hits(
        query="上下文优化有哪些策略",
        dense_hits=dense_hits,
        bm25_hits=bm25_hits,
        limit=3,
    )
    assert result[0]["chunk_id"] == "a"


def test_normalize_topic_tags_deduplicates_and_trims():
    result = normalize_topic_tags(
        [" LangGraph ", "状态机", "langgraph", "", " checkpoint ", "状态机", "断点续跑 "],
        limit=4,
    )
    assert result == ["LangGraph", "状态机", "checkpoint", "断点续跑"]


def test_pipeline_status_and_action_label():
    state = default_pipeline_state()
    assert pipeline_overall_status(state) == "pending"
    assert pipeline_action_label(state) == "开始处理"

    state["audio"]["status"] = "done"
    assert pipeline_overall_status(state) == "partial"
    assert pipeline_action_label(state) == "重试处理"

    state["transcript"]["status"] = "done"
    state["index"]["status"] = "done"
    assert pipeline_overall_status(state) == "indexed"
    assert pipeline_action_label(state) == "已转写入库"


def test_classify_query_intent_prefers_video_summary_when_bvid_present():
    result = classify_query_intent("总结一下这个视频", folder_id=10, bvid="BV1xx")
    assert result == {"intent": "video_summary", "scope": "video"}


def test_classify_query_intent_detects_folder_summary():
    result = classify_query_intent("帮我总结这个收藏夹都在讲什么", folder_id=10, bvid="BV1xx")
    assert result == {"intent": "folder_summary", "scope": "folder"}


def test_classify_query_intent_defaults_to_detail_qa():
    result = classify_query_intent("context window 是多少", folder_id=10, bvid="BV1xx")
    assert result == {"intent": "detail_qa", "scope": "folder"}


def test_pack_summary_windows_groups_by_accumulated_chars():
    windows = pack_summary_windows(
        [
            {"content": "a" * 1800},
            {"content": "b" * 1800},
            {"content": "c" * 1800},
        ],
        max_chars=4000,
    )
    assert len(windows) == 2
    assert len(windows[0]) == 2
    assert len(windows[1]) == 1


def test_pack_summary_documents_respects_doc_and_char_limits():
    groups = pack_summary_documents(
        [
            {"summary_text": "a" * 2000},
            {"summary_text": "b" * 2000},
            {"summary_text": "c" * 2000},
            {"summary_text": "d" * 2000},
        ],
        max_docs=2,
        max_chars=3500,
    )
    assert len(groups) == 4
    assert all(len(group) == 1 for group in groups)


class _FakeDb:
    def __init__(
        self,
        *,
        folders_by_uid=None,
        folder_rows=None,
        video_rows=None,
        state_updated_at=None,
    ):
        self.folders_by_uid = folders_by_uid or {}
        self.folder_rows = folder_rows or {}
        self.video_rows = video_rows or {}
        self.state_updated_at = state_updated_at or {}
        self.saved_states = {}
        self.upserted_videos = []

    def get_folders_by_uid(self, uid):
        return list(self.folders_by_uid.get(uid, []))

    def get_state_updated_at(self, key):
        return self.state_updated_at.get(key)

    def save_state(self, key, value):
        self.saved_states[key] = value
        self.state_updated_at[key] = datetime.now()

    def get_counts(self):
        return {"total_folders": 1, "total_videos": 2, "total_chunks": 3}

    def get_folder(self, folder_id):
        return self.folder_rows.get(folder_id)

    def get_video_records(self, folder_id):
        return list(self.video_rows.get(folder_id, []))

    def upsert_video(self, video):
        self.upserted_videos.append(dict(video))
        folder_id = int(video["folder_id"])
        current = list(self.video_rows.get(folder_id, []))
        current = [item for item in current if item.get("bvid") != video.get("bvid")]
        current.append(dict(video))
        self.video_rows[folder_id] = current


class _FakeBili:
    def __init__(self, *, folders=None, videos=None):
        self.folders = folders or []
        self.videos = videos or []
        self.list_folders_calls = 0
        self.list_folder_videos_calls = 0

    async def get_session(self):
        return {"logged_in": True, "uid": 1, "user_name": "tester"}

    async def list_folders(self, uid):
        self.list_folders_calls += 1
        return list(self.folders)

    async def list_folder_videos(self, folder_id):
        self.list_folder_videos_calls += 1
        return list(self.videos)


def test_build_folders_payload_uses_fresh_cache_without_hitting_bili():
    db = _FakeDb(
        folders_by_uid={
            1: [
                {
                    "folder_id": 10,
                    "title": "AI 收藏夹",
                    "media_count": 8,
                    "last_synced_at": "2026-03-24 00:00:00",
                    "synced_chunk_count": 12,
                    "synced_videos": 3,
                }
            ]
        },
        state_updated_at={folder_list_cache_key(1): datetime.now()},
    )
    bili = _FakeBili()
    runtime = SimpleNamespace(
        settings=SimpleNamespace(folder_list_cache_ttl_seconds=300, folder_videos_cache_ttl_seconds=300),
        db=db,
        bili=bili,
        cache_tasks={},
    )

    payload = asyncio.run(build_folders_payload(runtime, 1))

    assert payload["cached"] is True
    assert payload["stale"] is False
    assert bili.list_folders_calls == 0
    assert payload["folders"][0]["folder_id"] == 10


def test_build_folder_videos_payload_returns_stale_cache_and_refreshes_in_background():
    folder_id = 10
    db = _FakeDb(
        folder_rows={folder_id: {"folder_id": folder_id, "title": "AI 收藏夹", "media_count": 1}},
        video_rows={
            folder_id: [
                {
                    "bvid": "BV-old",
                    "folder_id": folder_id,
                    "title": "旧视频",
                }
            ]
        },
        state_updated_at={folder_videos_cache_key(folder_id): datetime.now() - timedelta(minutes=10)},
    )
    bili = _FakeBili(
        videos=[
            {
                "bvid": "BV-new",
                "title": "新视频",
                "duration": 120,
            }
        ]
    )
    runtime = SimpleNamespace(
        settings=SimpleNamespace(folder_list_cache_ttl_seconds=300, folder_videos_cache_ttl_seconds=300),
        db=db,
        bili=bili,
        cache_tasks={},
    )

    async def scenario():
        payload = await build_folder_videos_payload(runtime, folder_id)
        assert payload["cached"] is True
        assert payload["stale"] is True
        assert payload["videos"][0]["bvid"] == "BV-old"
        if runtime.cache_tasks:
            await asyncio.gather(*runtime.cache_tasks.values(), return_exceptions=True)

    asyncio.run(scenario())

    assert bili.list_folder_videos_calls == 1
    assert any(item["bvid"] == "BV-new" for item in db.upserted_videos)
    assert folder_videos_cache_key(folder_id) in db.saved_states
