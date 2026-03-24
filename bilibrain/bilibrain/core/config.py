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
    dashscope_api_key: str
    dashscope_base_url: str
    llm_model: str
    asr_model: str
    asr_language: str
    asr_chunk_seconds: int
    asr_target_chunk_seconds: int
    asr_chunk_overlap_seconds: float
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
    subtitle_merge_max_gap: float
    subtitle_merge_max_duration: float
    subtitle_chunk_target_chars: int
    subtitle_chunk_min_chars: int
    subtitle_chunk_overlap_chars: int
    subtitle_chunk_max_tokens: int
    default_max_video_minutes: int
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
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
        dashscope_base_url=os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ).rstrip("/"),
        llm_model=os.getenv("LLM_MODEL", "qwen-plus"),
        asr_model=os.getenv("ASR_MODEL", "qwen3-asr-flash"),
        asr_language=os.getenv("ASR_LANGUAGE", "zh").strip(),
        asr_chunk_seconds=_int("ASR_CHUNK_SECONDS", 120),
        asr_target_chunk_seconds=_int("ASR_TARGET_CHUNK_SECONDS", 90),
        asr_chunk_overlap_seconds=_float("ASR_CHUNK_OVERLAP_SECONDS", 1.0),
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
        subtitle_merge_max_gap=_float("SUBTITLE_MERGE_MAX_GAP", 2.0),
        subtitle_merge_max_duration=_float("SUBTITLE_MERGE_MAX_DURATION", 480.0),
        subtitle_chunk_target_chars=_int("SUBTITLE_CHUNK_TARGET_CHARS", 220),
        subtitle_chunk_min_chars=_int("SUBTITLE_CHUNK_MIN_CHARS", 80),
        subtitle_chunk_overlap_chars=_int("SUBTITLE_CHUNK_OVERLAP_CHARS", 50),
        subtitle_chunk_max_tokens=_int("SUBTITLE_CHUNK_MAX_TOKENS", 600),
        default_max_video_minutes=_int("DEFAULT_MAX_VIDEO_MINUTES", 30),
        audio_cache_dir=BASE_DIR / "data" / "audio",
        frontend_dist_dir=WORKSPACE_DIR / "frontend" / "dist",
        index_file=(
            (WORKSPACE_DIR / "frontend" / "dist" / "index.html")
            if (WORKSPACE_DIR / "frontend" / "dist" / "index.html").exists()
            else BASE_DIR / "index.html"
        ),
    )
