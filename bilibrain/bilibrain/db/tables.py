from sqlalchemy import (
    MetaData,
    Table,
    Column,
    Integer,
    BigInteger,
    String,
    Text,
    DateTime,
)

metadata = MetaData()

app_state = Table(
    "app_state",
    metadata,
    Column("state_key", String(128), primary_key=True),
    Column("state_value", Text, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

folders = Table(
    "folders",
    metadata,
    Column("folder_id", BigInteger, primary_key=True),
    Column("uid", BigInteger, nullable=False),
    Column("title", String(512), nullable=False),
    Column("media_count", Integer, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    Column("created_at", DateTime, nullable=False),
)

videos = Table(
    "videos",
    metadata,
    Column("bvid", String(32), primary_key=True),
    Column("folder_id", BigInteger, nullable=False),
    Column("title", String(512), nullable=False),
    Column("up_name", String(255)),
    Column("cover_url", String(1024)),
    Column("duration", Integer, nullable=False),
    Column("published_at", DateTime),
    Column("cid", BigInteger),
    Column("subtitle_source", String(64)),
    Column("manual_tags", String(512)),
    Column("synced_at", DateTime),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    Column("audio_storage_provider", String(32)),
    Column("audio_object_key", String(1024)),
    Column("audio_uploaded_at", DateTime),
    Column("is_invalid", Integer, nullable=False),
)

transcripts = Table(
    "transcripts",
    metadata,
    Column("bvid", String(32), primary_key=True),
    Column("source_model", String(128), nullable=False),
    Column("transcript_text", Text, nullable=False),
    Column("segments_json", Text, nullable=False),
    Column("segment_count", Integer, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

video_summaries = Table(
    "video_summaries",
    metadata,
    Column("bvid", String(32), primary_key=True),
    Column("transcript_hash", String(64), nullable=False),
    Column("summary_text", Text, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

video_pipeline = Table(
    "video_pipeline",
    metadata,
    Column("bvid", String(32), primary_key=True),
    Column("overall_status", String(32), nullable=False),
    Column("index_chunk_count", Integer, nullable=False),
    Column("state_json", Text),
    Column("updated_at", DateTime, nullable=False),
)

ingestion_batches = Table(
    "ingestion_batches",
    metadata,
    Column("batch_id", BigInteger, primary_key=True, autoincrement=True),
    Column("batch_type", String(32), nullable=False),
    Column("title", String(255)),
    Column("options_json", Text),
    Column("created_at", DateTime, nullable=False),
)

ingestion_tasks = Table(
    "ingestion_tasks",
    metadata,
    Column("task_id", BigInteger, primary_key=True, autoincrement=True),
    Column("batch_id", BigInteger),
    Column("bvid", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("last_error", Text),
    Column("options_json", Text),
    Column("worker_id", String(64)),
    Column("locked_at", DateTime),
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

tool_workspaces = Table(
    "tool_workspaces",
    metadata,
    Column("workspace_id", String(64), primary_key=True),
    Column("scope_key", String(255), nullable=False),
    Column("feature_name", String(128), nullable=False),
    Column("conversation_id", BigInteger),
    Column("title", String(255)),
    Column("actor", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("metadata_json", Text),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)

tool_calls = Table(
    "tool_calls",
    metadata,
    Column("call_id", BigInteger, primary_key=True, autoincrement=True),
    Column("trace_id", String(64), nullable=False),
    Column("workspace_id", String(64), nullable=False),
    Column("tool_name", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("arguments_json", Text),
    Column("result_json", Text),
    Column("error_json", Text),
    Column("duration_ms", Integer),
    Column("actor", String(64), nullable=False),
    Column("approval_mode", String(32), nullable=False),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
    Column("created_at", DateTime, nullable=False),
)

skill_activations = Table(
    "skill_activations",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("skill_name", String(128), unique=True, nullable=False),
    Column("activated_at", DateTime, nullable=False),
    Column("deactivated_at", DateTime),
)
