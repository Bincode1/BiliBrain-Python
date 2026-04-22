from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from bilibrain.core.config import Settings
from bilibrain.services.common import (
    normalize_pipeline_state,
    parse_manual_tags,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_datetime(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


# ---------------------------------------------------------------------------
# DDL (SQLite compatible)
# ---------------------------------------------------------------------------

_TABLE_DDLS = [
    """CREATE TABLE IF NOT EXISTS app_state (
        state_key VARCHAR(128) NOT NULL PRIMARY KEY,
        state_value TEXT NOT NULL,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS folders (
        folder_id INTEGER NOT NULL PRIMARY KEY,
        uid INTEGER NOT NULL,
        title VARCHAR(512) NOT NULL DEFAULT '',
        media_count INTEGER NOT NULL DEFAULT 0,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS videos (
        bvid VARCHAR(32) NOT NULL PRIMARY KEY,
        folder_id INTEGER NOT NULL,
        title VARCHAR(512) NOT NULL DEFAULT '',
        up_name VARCHAR(255) DEFAULT NULL,
        cover_url VARCHAR(1024) DEFAULT NULL,
        duration INTEGER NOT NULL DEFAULT 0,
        published_at DATETIME DEFAULT NULL,
        cid INTEGER DEFAULT NULL,
        subtitle_source VARCHAR(64) DEFAULT NULL,
        manual_tags VARCHAR(512) DEFAULT NULL,
        synced_at DATETIME DEFAULT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS transcripts (
        bvid VARCHAR(32) NOT NULL PRIMARY KEY,
        source_model VARCHAR(128) NOT NULL DEFAULT '',
        transcript_text TEXT NOT NULL,
        segments_json TEXT NOT NULL,
        segment_count INTEGER NOT NULL DEFAULT 0,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS video_summaries (
        bvid VARCHAR(32) NOT NULL PRIMARY KEY,
        transcript_hash VARCHAR(64) NOT NULL DEFAULT '',
        summary_text TEXT NOT NULL,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS video_pipeline (
        bvid VARCHAR(32) NOT NULL PRIMARY KEY,
        overall_status VARCHAR(32) NOT NULL DEFAULT 'pending',
        index_chunk_count INTEGER NOT NULL DEFAULT 0,
        state_json TEXT,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS ingestion_batches (
        batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_type VARCHAR(32) NOT NULL DEFAULT 'video_batch',
        title VARCHAR(255) DEFAULT NULL,
        options_json TEXT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS ingestion_tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id INTEGER DEFAULT NULL,
        bvid VARCHAR(32) NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'queued',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        options_json TEXT,
        worker_id VARCHAR(64) DEFAULT NULL,
        locked_at DATETIME DEFAULT NULL,
        started_at DATETIME DEFAULT NULL,
        finished_at DATETIME DEFAULT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS tool_workspaces (
        workspace_id VARCHAR(64) NOT NULL PRIMARY KEY,
        scope_key VARCHAR(255) NOT NULL DEFAULT '',
        feature_name VARCHAR(128) NOT NULL DEFAULT '',
        conversation_id INTEGER DEFAULT NULL,
        title VARCHAR(255) DEFAULT NULL,
        actor VARCHAR(64) NOT NULL DEFAULT 'system',
        status VARCHAR(32) NOT NULL DEFAULT 'active',
        metadata_json TEXT,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS tool_calls (
        call_id INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_id VARCHAR(64) NOT NULL DEFAULT '',
        workspace_id VARCHAR(64) NOT NULL,
        tool_name VARCHAR(128) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        arguments_json TEXT,
        result_json TEXT,
        error_json TEXT,
        duration_ms INTEGER DEFAULT NULL,
        actor VARCHAR(64) NOT NULL DEFAULT 'system',
        approval_mode VARCHAR(32) NOT NULL DEFAULT 'auto',
        started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at DATETIME DEFAULT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS skill_activations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        skill_name VARCHAR(128) UNIQUE NOT NULL,
        activated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        deactivated_at DATETIME DEFAULT NULL
    )""",

]

_INDEX_DDLS = [
    "CREATE INDEX IF NOT EXISTS idx_folders_uid ON folders (uid)",
    "CREATE INDEX IF NOT EXISTS idx_videos_folder ON videos (folder_id)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON ingestion_tasks (status)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_bvid ON ingestion_tasks (bvid)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_batch ON ingestion_tasks (batch_id)",
    "CREATE INDEX IF NOT EXISTS idx_ws_scope ON tool_workspaces (scope_key)",
    "CREATE INDEX IF NOT EXISTS idx_ws_feature ON tool_workspaces (feature_name)",
    "CREATE INDEX IF NOT EXISTS idx_tc_workspace ON tool_calls (workspace_id)",
]


# ---------------------------------------------------------------------------
# Database facade
# ---------------------------------------------------------------------------


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._engine: AsyncEngine | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError(
                "Database engine not initialized. Call ensure_ready() first."
            )
        return self._engine

    async def ensure_ready(self) -> None:
        if self._engine is not None:
            return
        self.settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_async_engine(
            f"sqlite+aiosqlite:///{self.settings.db_path}?timeout=30",
            pool_pre_ping=True,
        )
        async with self._engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            await conn.run_sync(self._create_tables)
            await conn.run_sync(self._create_indexes)
            await conn.run_sync(self._ensure_video_columns)
            await conn.run_sync(self._ensure_folder_columns)

    async def close(self) -> None:
        if self._engine is None:
            return
        await self._engine.dispose()
        self._engine = None

    def _create_tables(self, conn: Any) -> None:
        for ddl in _TABLE_DDLS:
            conn.execute(text(ddl))

    def _create_indexes(self, conn: Any) -> None:
        for ddl in _INDEX_DDLS:
            conn.execute(text(ddl))

    def _ensure_video_columns(self, conn: Any) -> None:
        columns = {
            "audio_storage_provider": "VARCHAR(32) DEFAULT NULL",
            "audio_object_key": "VARCHAR(1024) DEFAULT NULL",
            "audio_uploaded_at": "DATETIME DEFAULT NULL",
            "is_invalid": "INTEGER NOT NULL DEFAULT 0",
        }
        for col, col_def in columns.items():
            try:
                conn.execute(text(f"ALTER TABLE videos ADD COLUMN {col} {col_def}"))
            except Exception:
                pass

    def _ensure_folder_columns(self, conn: Any) -> None:
        columns = {
            "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        }
        for col, col_def in columns.items():
            try:
                conn.execute(text(f"ALTER TABLE folders ADD COLUMN {col} {col_def}"))
            except Exception:
                pass

    # -- formatting helpers (used by query modules) ------------------------

    @staticmethod
    def _hydrate_pipeline_state(
        *,
        bvid: str,
        raw_state_json: str | None,
        transcript_source: str | None,
        transcript_segment_count: Any,
        transcript_updated_at: Any,
        audio_storage_provider: str | None,
        audio_object_key: str | None,
        audio_uploaded_at: Any,
        synced_at: Any = None,
    ) -> dict[str, dict[str, Any]]:
        raw_state = json.loads(raw_state_json) if raw_state_json else None
        state = normalize_pipeline_state(raw_state)
        if (
            audio_storage_provider
            and audio_object_key
            and state["audio"]["status"] == "pending"
        ):
            state["audio"].update(
                {
                    "status": "done",
                    "provider": audio_storage_provider,
                    "object_key": audio_object_key,
                    "path": f"{audio_storage_provider}://{audio_object_key}",
                    "updated_at": _format_datetime(audio_uploaded_at),
                }
            )
        if transcript_source and state["transcript"]["status"] == "pending":
            state["transcript"].update(
                {
                    "status": "done",
                    "source_model": transcript_source,
                    "segment_count": int(transcript_segment_count or 0),
                    "updated_at": _format_datetime(transcript_updated_at),
                }
            )
        if (
            synced_at
            and state["audio"]["status"] == "done"
            and state["transcript"]["status"] == "done"
            and state["index"]["status"] == "pending"
        ):
            state["index"].update(
                {
                    "status": "done",
                    "updated_at": _format_datetime(synced_at),
                }
            )
        return normalize_pipeline_state(state)

    @staticmethod
    def _format_ingestion_batch(row: dict[str, Any]) -> dict[str, Any]:
        options_json = row.get("options_json")
        try:
            options = json.loads(options_json) if options_json else {}
        except json.JSONDecodeError:
            options = {}
        return {
            "batch_id": int(row["batch_id"]),
            "batch_type": str(row.get("batch_type") or "").strip() or "video_batch",
            "title": str(row.get("title") or "").strip(),
            "options": options if isinstance(options, dict) else {},
            "created_at": _format_datetime(row.get("created_at")),
        }

    @staticmethod
    def _format_ingestion_task(row: dict[str, Any]) -> dict[str, Any]:
        options_json = row.get("options_json")
        try:
            options = json.loads(options_json) if options_json else {}
        except json.JSONDecodeError:
            options = {}
        return {
            "task_id": int(row["task_id"]),
            "batch_id": int(row["batch_id"])
            if row.get("batch_id") is not None
            else None,
            "bvid": str(row.get("bvid") or "").strip(),
            "status": str(row.get("status") or "").strip().lower() or "queued",
            "attempt_count": int(row.get("attempt_count") or 0),
            "last_error": str(row.get("last_error") or "").strip(),
            "options": options if isinstance(options, dict) else {},
            "worker_id": str(row.get("worker_id") or "").strip() or None,
            "locked_at": _format_datetime(row.get("locked_at")),
            "started_at": _format_datetime(row.get("started_at")),
            "finished_at": _format_datetime(row.get("finished_at")),
            "created_at": _format_datetime(row.get("created_at")),
            "updated_at": _format_datetime(row.get("updated_at")),
        }

    @staticmethod
    def _format_tool_call(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "call_id": int(row["call_id"]),
            "trace_id": str(row.get("trace_id") or ""),
            "workspace_id": str(row["workspace_id"]),
            "tool_name": str(row["tool_name"]),
            "actor": str(row.get("actor") or ""),
            "approval_mode": str(row.get("approval_mode") or ""),
            "status": str(row["status"]),
            "arguments": json.loads(row["arguments_json"])
            if row.get("arguments_json")
            else {},
            "result": json.loads(row["result_json"])
            if row.get("result_json")
            else None,
            "error": json.loads(row["error_json"]) if row.get("error_json") else None,
            "duration_ms": round(float(row.get("duration_ms") or 0.0), 3),
            "started_at": _format_datetime(row.get("started_at")),
            "finished_at": _format_datetime(row.get("finished_at")),
            "created_at": _format_datetime(row.get("created_at")),
        }


# ---------------------------------------------------------------------------
# Mix in query methods from sub-modules
# ---------------------------------------------------------------------------
from bilibrain.db.queries.state import (  # noqa: E402
    save_state,
    load_state,
    get_state_updated_at,
    get_processing_settings,
    save_processing_settings,
    try_acquire_state_lease,
    release_state_lease,
)
from bilibrain.db.queries.collections import (  # noqa: E402
    save_folders,
    get_folders_by_uid,
    get_folder,
    get_video_records,
    get_video,
    upsert_video,
    set_video_tags,
    mark_video_processed,
    clear_video_processing_markers,
    reset_video_processing_artifacts,
    list_all_video_bvids,
    list_all_audio_objects,
)
from bilibrain.db.queries.transcripts import (  # noqa: E402
    get_transcript,
    save_transcript,
    delete_transcript,
    delete_all_transcripts,
    get_video_summary,
    list_video_summaries,
    search_video_summaries,
    save_video_summary,
    delete_video_summary,
    delete_all_video_summaries,
    get_pipeline_state,
    get_pipeline_overall_statuses,
    save_pipeline_state,
    update_pipeline_step,
    reset_pipeline_state,
    reset_all_pipeline_states,
    clear_all_video_processing_markers,
)
from bilibrain.db.queries.ingestion import (  # noqa: E402
    create_ingestion_batch,
    get_ingestion_batch,
    list_ingestion_batches,
    create_ingestion_task,
    list_ingestion_tasks,
    get_ingestion_task,
    get_active_ingestion_task_for_bvid,
    claim_next_ingestion_task,
    mark_ingestion_task_succeeded,
    mark_ingestion_task_failed,
    mark_ingestion_task_stale,
    touch_ingestion_task_lock,
    mark_stale_ingestion_tasks,
    cancel_ingestion_task,
    delete_ingestion_tasks_for_bvid,
    delete_all_ingestion_tasks,
)
from bilibrain.db.queries.chat import (  # noqa: E402
    create_tool_workspace,
    ensure_default_tool_workspace,
    get_tool_workspace_by_scope_key,
    get_tool_workspace,
    list_tool_workspaces,
    log_tool_call,
    list_tool_calls_for_conversation,
    get_counts,
)
from bilibrain.db.queries.skills import (  # noqa: E402
    activate_skill,
    deactivate_skill,
    get_active_skills,
)

Database.save_state = save_state  # type: ignore[method-assign]
Database.load_state = load_state  # type: ignore[method-assign]
Database.get_state_updated_at = get_state_updated_at  # type: ignore[method-assign]
Database.get_processing_settings = get_processing_settings  # type: ignore[method-assign]
Database.save_processing_settings = save_processing_settings  # type: ignore[method-assign]
Database.try_acquire_state_lease = try_acquire_state_lease  # type: ignore[method-assign]
Database.release_state_lease = release_state_lease  # type: ignore[method-assign]
Database.save_folders = save_folders  # type: ignore[method-assign]
Database.get_folders_by_uid = get_folders_by_uid  # type: ignore[method-assign]
Database.get_folder = get_folder  # type: ignore[method-assign]
Database.get_video_records = get_video_records  # type: ignore[method-assign]
Database.get_video = get_video  # type: ignore[method-assign]
Database.upsert_video = upsert_video  # type: ignore[method-assign]
Database.set_video_tags = set_video_tags  # type: ignore[method-assign]
Database.mark_video_processed = mark_video_processed  # type: ignore[method-assign]
Database.clear_video_processing_markers = clear_video_processing_markers  # type: ignore[method-assign]
Database.reset_video_processing_artifacts = reset_video_processing_artifacts  # type: ignore[method-assign]
Database.list_all_video_bvids = list_all_video_bvids  # type: ignore[method-assign]
Database.list_all_audio_objects = list_all_audio_objects  # type: ignore[method-assign]
Database.get_transcript = get_transcript  # type: ignore[method-assign]
Database.save_transcript = save_transcript  # type: ignore[method-assign]
Database.delete_transcript = delete_transcript  # type: ignore[method-assign]
Database.delete_all_transcripts = delete_all_transcripts  # type: ignore[method-assign]
Database.get_video_summary = get_video_summary  # type: ignore[method-assign]
Database.list_video_summaries = list_video_summaries  # type: ignore[method-assign]
Database.search_video_summaries = search_video_summaries  # type: ignore[method-assign]
Database.save_video_summary = save_video_summary  # type: ignore[method-assign]
Database.delete_video_summary = delete_video_summary  # type: ignore[method-assign]
Database.delete_all_video_summaries = delete_all_video_summaries  # type: ignore[method-assign]
Database.get_pipeline_state = get_pipeline_state  # type: ignore[method-assign]
Database.get_pipeline_overall_statuses = get_pipeline_overall_statuses  # type: ignore[method-assign]
Database.save_pipeline_state = save_pipeline_state  # type: ignore[method-assign]
Database.update_pipeline_step = update_pipeline_step  # type: ignore[method-assign]
Database.reset_pipeline_state = reset_pipeline_state  # type: ignore[method-assign]
Database.reset_all_pipeline_states = reset_all_pipeline_states  # type: ignore[method-assign]
Database.clear_all_video_processing_markers = clear_all_video_processing_markers  # type: ignore[method-assign]
Database.create_ingestion_batch = create_ingestion_batch  # type: ignore[method-assign]
Database.get_ingestion_batch = get_ingestion_batch  # type: ignore[method-assign]
Database.list_ingestion_batches = list_ingestion_batches  # type: ignore[method-assign]
Database.create_ingestion_task = create_ingestion_task  # type: ignore[method-assign]
Database.list_ingestion_tasks = list_ingestion_tasks  # type: ignore[method-assign]
Database.get_ingestion_task = get_ingestion_task  # type: ignore[method-assign]
Database.get_active_ingestion_task_for_bvid = get_active_ingestion_task_for_bvid  # type: ignore[method-assign]
Database.claim_next_ingestion_task = claim_next_ingestion_task  # type: ignore[method-assign]
Database.mark_ingestion_task_succeeded = mark_ingestion_task_succeeded  # type: ignore[method-assign]
Database.mark_ingestion_task_failed = mark_ingestion_task_failed  # type: ignore[method-assign]
Database.mark_ingestion_task_stale = mark_ingestion_task_stale  # type: ignore[method-assign]
Database.touch_ingestion_task_lock = touch_ingestion_task_lock  # type: ignore[method-assign]
Database.mark_stale_ingestion_tasks = mark_stale_ingestion_tasks  # type: ignore[method-assign]
Database.cancel_ingestion_task = cancel_ingestion_task  # type: ignore[method-assign]
Database.delete_ingestion_tasks_for_bvid = delete_ingestion_tasks_for_bvid  # type: ignore[method-assign]
Database.delete_all_ingestion_tasks = delete_all_ingestion_tasks  # type: ignore[method-assign]
Database.create_tool_workspace = create_tool_workspace  # type: ignore[method-assign]
Database.ensure_default_tool_workspace = ensure_default_tool_workspace  # type: ignore[method-assign]
Database.get_tool_workspace_by_scope_key = get_tool_workspace_by_scope_key  # type: ignore[method-assign]
Database.get_tool_workspace = get_tool_workspace  # type: ignore[method-assign]
Database.list_tool_workspaces = list_tool_workspaces  # type: ignore[method-assign]
Database.log_tool_call = log_tool_call  # type: ignore[method-assign]
Database.list_tool_calls_for_conversation = list_tool_calls_for_conversation  # type: ignore[method-assign]
Database.get_counts = get_counts  # type: ignore[method-assign]
Database.activate_skill = activate_skill  # type: ignore[method-assign]
Database.deactivate_skill = deactivate_skill  # type: ignore[method-assign]
Database.get_active_skills = get_active_skills  # type: ignore[method-assign]
