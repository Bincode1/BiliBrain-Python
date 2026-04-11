from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from bilibrain.core.config import Settings


@dataclass(frozen=True)
class AudioObjectRef:
    provider: str
    object_key: str
    url: str | None = None


class AudioStorageService:
    provider_name = "local"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_dir = settings.audio_dir

    def _upload_audio_sync(self, source_path: Path, *, bvid: str) -> AudioObjectRef:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        object_key = f"{bvid}.m4a"
        destination = self.base_dir / object_key
        shutil.copy2(source_path, destination)
        return AudioObjectRef(
            provider=self.provider_name,
            object_key=object_key,
            url=f"/storage/audio/{quote(object_key)}",
        )

    def _download_audio_sync(self, object_key: str, target_path: Path) -> Path:
        source = self.base_dir / object_key
        if not source.exists():
            raise RuntimeError("本地音频对象不存在。")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_path)
        return target_path

    def _delete_audio_sync(self, object_key: str) -> None:
        target = self.base_dir / object_key
        if target.exists():
            target.unlink()

    def get_audio_url(self, object_key: str | None) -> str | None:
        if not object_key:
            return None
        return f"/storage/audio/{quote(object_key)}"

    async def upload_audio(self, source_path: Path, *, bvid: str) -> AudioObjectRef:
        return await asyncio.to_thread(self._upload_audio_sync, source_path, bvid=bvid)

    async def download_audio(self, provider_name: str, object_key: str, target_path: Path) -> Path:
        return await asyncio.to_thread(self._download_audio_sync, object_key, target_path)

    async def delete_audio(self, provider_name: str, object_key: str) -> None:
        await asyncio.to_thread(self._delete_audio_sync, object_key)
