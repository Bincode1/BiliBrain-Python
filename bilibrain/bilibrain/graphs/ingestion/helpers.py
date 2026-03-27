from __future__ import annotations

from pathlib import Path
from typing import Any

from bilibrain.core.runtime import Runtime
from bilibrain.services.common import build_segment_inputs


def audio_display_path(provider: str | None, object_key: str | None) -> str | None:
    if not provider or not object_key:
        return None
    if provider == "local":
        return f"local://{object_key}"
    return f"{provider}://{object_key}"


def duration_limit_message(duration_seconds: int, max_minutes: int) -> str:
    actual_minutes = max(duration_seconds / 60, 0)
    return f"视频时长 {actual_minutes:.1f} 分钟，超过当前 {max_minutes} 分钟限制。"


def require_video(runtime: Runtime, bvid: str) -> dict[str, Any]:
    video = runtime.db.get_video(bvid)
    if not video:
        raise RuntimeError("找不到这个视频，请先读取收藏夹内容。")
    return video


def ensure_processable_video(video: dict[str, Any]) -> None:
    if bool(video.get("is_invalid")):
        raise RuntimeError("失效视频无法处理。")


def hydrate_audio_step_state(runtime: Runtime, video: dict[str, Any] | None, state: dict[str, dict[str, Any]]) -> None:
    if state["audio"]["status"] != "pending":
        return
    provider = (video or {}).get("audio_storage_provider")
    object_key = (video or {}).get("audio_object_key")
    if provider and object_key:
        state["audio"].update(
            {
                "status": "done",
                "provider": provider,
                "object_key": object_key,
                "path": audio_display_path(provider, object_key),
                "url": runtime.audio_storage.get_audio_url(provider, object_key),
            }
        )


async def prepare_audio_input_file(runtime: Runtime, video: dict[str, Any], target_path: Path) -> Path:
    provider = video.get("audio_storage_provider")
    object_key = video.get("audio_object_key")
    if provider and object_key:
        return await runtime.audio_storage.download_audio(str(provider), str(object_key), target_path)
    raise RuntimeError("音频对象不存在，请重试。")
