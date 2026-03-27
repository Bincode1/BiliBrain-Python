from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = BASE_DIR.parent
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _command_prefixes(name: str, default: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
    value = os.getenv(name)
    if value is None:
        return default
    prefixes: list[tuple[str, ...]] = []
    for raw_prefix in value.split(";"):
        parts = tuple(part.strip() for part in raw_prefix.split() if part.strip())
        if parts:
            prefixes.append(parts)
    return tuple(prefixes)


@dataclass(frozen=True)
class Settings:
    app_name: str
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    milvus_host: str
    milvus_port: int
    milvus_user: str
    milvus_password: str
    milvus_database: str
    milvus_collection: str
    milvus_dimension: int
    tavily_api_key: str
    tavily_mcp_url: str
    dashscope_api_key: str
    dashscope_base_url: str
    llm_model: str
    planner_llm_model: str
    asr_model: str
    asr_language: str
    asr_chunk_seconds: int
    asr_target_chunk_seconds: int
    asr_chunk_overlap_seconds: float
    asr_chunk_concurrency: int
    asr_silence_min_seconds: float
    asr_silence_noise_db: float
    ollama_base_url: str
    embedding_model: str
    bili_api_delay: float
    audio_storage_provider: str
    audio_storage_bucket: str
    audio_storage_prefix: str
    audio_storage_endpoint: str
    audio_storage_region: str
    audio_storage_access_key: str
    audio_storage_secret_key: str
    audio_storage_public_base_url: str
    audio_storage_presign_seconds: int
    audio_storage_force_path_style: bool
    session_cache_ttl_seconds: int
    folder_list_cache_ttl_seconds: int
    folder_videos_cache_ttl_seconds: int
    transcript_merge_max_gap: float
    transcript_merge_max_duration: float
    transcript_chunk_target_chars: int
    transcript_chunk_min_chars: int
    transcript_chunk_overlap_chars: int
    transcript_chunk_max_tokens: int
    default_max_video_minutes: int
    chat_recent_turns_to_keep: int
    chat_compaction_trigger_tokens: int
    ingestion_max_concurrency: int
    reset_max_concurrency: int
    ingestion_poll_interval_seconds: float
    ingestion_task_stale_after_seconds: int
    ragas_dataset_root: Path
    ragas_experiment_root: Path
    ragas_run_timeout_seconds: int
    ragas_run_max_retries: int
    ragas_run_max_workers: int
    ragas_enable_answer_relevancy: bool
    tools_enabled: bool
    tools_runtime: str
    tools_workspace_root: Path
    tools_default_timeout_seconds: int
    tools_max_stdout_bytes: int
    tools_max_stderr_bytes: int
    tools_approval_required_for_write: bool
    tools_approval_required_for_command: bool
    tools_allowed_command_prefixes: tuple[tuple[str, ...], ...]
    tools_blocked_command_prefixes: tuple[tuple[str, ...], ...]
    tools_docker_bin: str
    tools_docker_image: str
    tools_docker_user: str
    tools_docker_workspace_mount_path: str
    tools_docker_shell: str
    tools_docker_read_only_rootfs: bool
    tools_docker_network_disabled: bool
    tools_docker_memory_limit_mb: int
    tools_docker_cpu_limit: float
    tools_docker_pids_limit: int
    tools_docker_tmpfs_size_mb: int
    skills_enabled: bool
    skills_builtin_root: Path
    skills_user_root: Path
    skills_repo_root: Path
    skills_user_enabled: bool
    skills_repo_enabled: bool
    skills_trust_repo: bool
    audio_cache_dir: Path
    frontend_dist_dir: Path
    index_file: Path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "BiliBrain"),
        mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        mysql_port=_int("MYSQL_PORT", 3306),
        mysql_user=os.getenv("MYSQL_USER", "root"),
        mysql_password=os.getenv("MYSQL_PASSWORD", ""),
        mysql_database=os.getenv("MYSQL_DATABASE", "bilibrain"),
        milvus_host=os.getenv("MILVUS_HOST", "127.0.0.1"),
        milvus_port=_int("MILVUS_PORT", 19530),
        milvus_user=os.getenv("MILVUS_USER", ""),
        milvus_password=os.getenv("MILVUS_PASSWORD", ""),
        milvus_database=os.getenv("MILVUS_DATABASE", "default"),
        milvus_collection=os.getenv("MILVUS_COLLECTION", "bili_chunks"),
        milvus_dimension=_int("MILVUS_DIMENSION", 1024),
        tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
        tavily_mcp_url=os.getenv("TAVILY_MCP_URL", "https://mcp.tavily.com/mcp/").strip().rstrip("/"),
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
        dashscope_base_url=os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ).rstrip("/"),
        llm_model=os.getenv("LLM_MODEL", "qwen-plus"),
        planner_llm_model=os.getenv("PLANNER_LLM_MODEL", os.getenv("LLM_MODEL", "qwen-plus")).strip(),
        asr_model=os.getenv("ASR_MODEL", "qwen3-asr-flash"),
        asr_language=os.getenv("ASR_LANGUAGE", "zh").strip(),
        asr_chunk_seconds=_int("ASR_CHUNK_SECONDS", 120),
        asr_target_chunk_seconds=_int("ASR_TARGET_CHUNK_SECONDS", 90),
        asr_chunk_overlap_seconds=_float("ASR_CHUNK_OVERLAP_SECONDS", 1.0),
        asr_chunk_concurrency=_int("ASR_CHUNK_CONCURRENCY", 2),
        asr_silence_min_seconds=_float("ASR_SILENCE_MIN_SECONDS", 0.6),
        asr_silence_noise_db=_float("ASR_SILENCE_NOISE_DB", -35.0),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "qwen3-embedding"),
        bili_api_delay=_float("BILI_API_DELAY", 1.0),
        audio_storage_provider=os.getenv("AUDIO_STORAGE_PROVIDER", "local").strip().lower(),
        audio_storage_bucket=os.getenv("AUDIO_STORAGE_BUCKET", "bilibrain-audio").strip(),
        audio_storage_prefix=os.getenv("AUDIO_STORAGE_PREFIX", "audio").strip().strip("/"),
        audio_storage_endpoint=os.getenv("AUDIO_STORAGE_ENDPOINT", "").strip().rstrip("/"),
        audio_storage_region=os.getenv("AUDIO_STORAGE_REGION", "us-east-1").strip(),
        audio_storage_access_key=os.getenv("AUDIO_STORAGE_ACCESS_KEY", "").strip(),
        audio_storage_secret_key=os.getenv("AUDIO_STORAGE_SECRET_KEY", "").strip(),
        audio_storage_public_base_url=os.getenv("AUDIO_STORAGE_PUBLIC_BASE_URL", "").strip().rstrip("/"),
        audio_storage_presign_seconds=_int("AUDIO_STORAGE_PRESIGN_SECONDS", 3600),
        audio_storage_force_path_style=_bool("AUDIO_STORAGE_FORCE_PATH_STYLE", True),
        session_cache_ttl_seconds=_int("SESSION_CACHE_TTL_SECONDS", 60),
        folder_list_cache_ttl_seconds=_int("FOLDER_LIST_CACHE_TTL_SECONDS", 300),
        folder_videos_cache_ttl_seconds=_int("FOLDER_VIDEOS_CACHE_TTL_SECONDS", 300),
        transcript_merge_max_gap=_float("TRANSCRIPT_MERGE_MAX_GAP", _float("SUBTITLE_MERGE_MAX_GAP", 2.0)),
        transcript_merge_max_duration=_float(
            "TRANSCRIPT_MERGE_MAX_DURATION",
            _float("SUBTITLE_MERGE_MAX_DURATION", 480.0),
        ),
        transcript_chunk_target_chars=_int(
            "TRANSCRIPT_CHUNK_TARGET_CHARS",
            _int("SUBTITLE_CHUNK_TARGET_CHARS", 220),
        ),
        transcript_chunk_min_chars=_int(
            "TRANSCRIPT_CHUNK_MIN_CHARS",
            _int("SUBTITLE_CHUNK_MIN_CHARS", 80),
        ),
        transcript_chunk_overlap_chars=_int(
            "TRANSCRIPT_CHUNK_OVERLAP_CHARS",
            _int("SUBTITLE_CHUNK_OVERLAP_CHARS", 50),
        ),
        transcript_chunk_max_tokens=_int(
            "TRANSCRIPT_CHUNK_MAX_TOKENS",
            _int("SUBTITLE_CHUNK_MAX_TOKENS", 600),
        ),
        default_max_video_minutes=_int("DEFAULT_MAX_VIDEO_MINUTES", 30),
        chat_recent_turns_to_keep=_int("CHAT_RECENT_TURNS_TO_KEEP", 5),
        chat_compaction_trigger_tokens=_int("CHAT_COMPACTION_TRIGGER_TOKENS", 50000),
        ingestion_max_concurrency=_int("INGESTION_MAX_CONCURRENCY", 3),
        reset_max_concurrency=_int("RESET_MAX_CONCURRENCY", 4),
        ingestion_poll_interval_seconds=_float("INGESTION_POLL_INTERVAL_SECONDS", 2.0),
        ingestion_task_stale_after_seconds=_int("INGESTION_TASK_STALE_AFTER_SECONDS", 1800),
        ragas_dataset_root=WORKSPACE_DIR / "bilibrain" / os.getenv("RAGAS_DATASET_ROOT", "datasets"),
        ragas_experiment_root=WORKSPACE_DIR / "bilibrain" / os.getenv("RAGAS_EXPERIMENT_ROOT", "experiments"),
        ragas_run_timeout_seconds=_int("RAGAS_RUN_TIMEOUT_SECONDS", 120),
        ragas_run_max_retries=_int("RAGAS_RUN_MAX_RETRIES", 3),
        ragas_run_max_workers=_int("RAGAS_RUN_MAX_WORKERS", 4),
        ragas_enable_answer_relevancy=_bool("RAGAS_ENABLE_ANSWER_RELEVANCY", False),
        tools_enabled=_bool("TOOLS_ENABLED", False),
        tools_runtime=os.getenv("TOOLS_RUNTIME", "local_dev").strip().lower(),
        tools_workspace_root=WORKSPACE_DIR / "bilibrain" / os.getenv("TOOLS_WORKSPACE_ROOT", "data/tool_workspaces"),
        tools_default_timeout_seconds=_int("TOOLS_DEFAULT_TIMEOUT_SECONDS", 30),
        tools_max_stdout_bytes=_int("TOOLS_MAX_STDOUT_BYTES", 65536),
        tools_max_stderr_bytes=_int("TOOLS_MAX_STDERR_BYTES", 65536),
        tools_approval_required_for_write=_bool("TOOLS_APPROVAL_REQUIRED_FOR_WRITE", False),
        tools_approval_required_for_command=_bool("TOOLS_APPROVAL_REQUIRED_FOR_COMMAND", False),
        tools_allowed_command_prefixes=_command_prefixes("TOOLS_ALLOWED_COMMAND_PREFIXES", ()),
        tools_blocked_command_prefixes=_command_prefixes(
            "TOOLS_BLOCKED_COMMAND_PREFIXES",
            (
                ("rm",),
                ("shutdown",),
                ("reboot",),
                ("poweroff",),
                ("mkfs",),
                ("diskpart",),
                ("format",),
            ),
        ),
        tools_docker_bin=os.getenv("TOOLS_DOCKER_BIN", "docker").strip(),
        tools_docker_image=os.getenv("TOOLS_DOCKER_IMAGE", "python:3.13-alpine").strip(),
        tools_docker_user=os.getenv("TOOLS_DOCKER_USER", "65532:65532").strip(),
        tools_docker_workspace_mount_path=os.getenv("TOOLS_DOCKER_WORKSPACE_MOUNT_PATH", "/workspace").strip(),
        tools_docker_shell=os.getenv("TOOLS_DOCKER_SHELL", "/bin/sh").strip(),
        tools_docker_read_only_rootfs=_bool("TOOLS_DOCKER_READ_ONLY_ROOTFS", True),
        tools_docker_network_disabled=_bool("TOOLS_DOCKER_NETWORK_DISABLED", True),
        tools_docker_memory_limit_mb=_int("TOOLS_DOCKER_MEMORY_LIMIT_MB", 512),
        tools_docker_cpu_limit=_float("TOOLS_DOCKER_CPU_LIMIT", 1.0),
        tools_docker_pids_limit=_int("TOOLS_DOCKER_PIDS_LIMIT", 128),
        tools_docker_tmpfs_size_mb=_int("TOOLS_DOCKER_TMPFS_SIZE_MB", 64),
        skills_enabled=_bool("SKILLS_ENABLED", True),
        skills_builtin_root=BASE_DIR / "bilibrain" / os.getenv("SKILLS_BUILTIN_ROOT", "builtin_skills"),
        skills_user_root=Path(os.getenv("SKILLS_USER_ROOT", str(Path.home() / ".bilibrain" / "skills"))),
        skills_repo_root=WORKSPACE_DIR / os.getenv("SKILLS_REPO_ROOT", ".agents/skills"),
        skills_user_enabled=_bool("SKILLS_USER_ENABLED", True),
        skills_repo_enabled=_bool("SKILLS_REPO_ENABLED", True),
        skills_trust_repo=_bool("SKILLS_TRUST_REPO", True),
        audio_cache_dir=BASE_DIR / "data" / "audio",
        frontend_dist_dir=WORKSPACE_DIR / "frontend" / "dist",
        index_file=(
            (WORKSPACE_DIR / "frontend" / "dist" / "index.html")
            if (WORKSPACE_DIR / "frontend" / "dist" / "index.html").exists()
            else BASE_DIR / "index.html"
        ),
    )
