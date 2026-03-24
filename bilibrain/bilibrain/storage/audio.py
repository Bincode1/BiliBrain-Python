from __future__ import annotations

import asyncio
import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from bilibrain.core.config import Settings


def _normalize_prefix(prefix: str) -> str:
    normalized = str(prefix or "").strip().strip("/")
    return normalized


@dataclass(frozen=True)
class AudioObjectRef:
    provider: str
    object_key: str
    url: str | None = None


class _BaseAudioProvider:
    provider_name: str

    def upload_audio(self, source_path: Path, *, bvid: str) -> AudioObjectRef:
        raise NotImplementedError

    def download_audio(self, object_key: str, target_path: Path) -> Path:
        raise NotImplementedError

    def delete_audio(self, object_key: str) -> None:
        raise NotImplementedError

    def get_audio_url(self, object_key: str) -> str | None:
        raise NotImplementedError


class _LocalAudioProvider(_BaseAudioProvider):
    provider_name = "local"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_dir = settings.audio_cache_dir

    def upload_audio(self, source_path: Path, *, bvid: str) -> AudioObjectRef:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        object_key = f"{bvid}.m4a"
        destination = self.base_dir / object_key
        shutil.copy2(source_path, destination)
        return AudioObjectRef(
            provider=self.provider_name,
            object_key=object_key,
            url=self.get_audio_url(object_key),
        )

    def download_audio(self, object_key: str, target_path: Path) -> Path:
        source = self.base_dir / object_key
        if not source.exists():
            raise RuntimeError("本地音频对象不存在。")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target_path)
        return target_path

    def delete_audio(self, object_key: str) -> None:
        target = self.base_dir / object_key
        if target.exists():
            target.unlink()

    def get_audio_url(self, object_key: str) -> str | None:
        return f"/storage/audio/{quote(object_key)}"


class _S3AudioProvider(_BaseAudioProvider):
    provider_name = "s3"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bucket = settings.audio_storage_bucket
        self.prefix = _normalize_prefix(settings.audio_storage_prefix)
        self._client: Any | None = None

    def _build_object_key(self, *, bvid: str) -> str:
        filename = f"{bvid}.m4a"
        return f"{self.prefix}/{filename}" if self.prefix else filename

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise RuntimeError("启用 S3 音频存储前请先安装 boto3。") from exc

        session = boto3.session.Session()
        self._client = session.client(
            "s3",
            region_name=self.settings.audio_storage_region,
            endpoint_url=self.settings.audio_storage_endpoint or None,
            aws_access_key_id=self.settings.audio_storage_access_key or None,
            aws_secret_access_key=self.settings.audio_storage_secret_key or None,
            config=Config(s3={"addressing_style": "path" if self.settings.audio_storage_force_path_style else "auto"}),
        )
        return self._client

    def upload_audio(self, source_path: Path, *, bvid: str) -> AudioObjectRef:
        client = self._get_client()
        object_key = self._build_object_key(bvid=bvid)
        extra_args: dict[str, Any] = {}
        content_type, _ = mimetypes.guess_type(source_path.name)
        if content_type:
            extra_args["ContentType"] = content_type
        client.upload_file(
            str(source_path),
            self.bucket,
            object_key,
            ExtraArgs=extra_args or None,
        )
        return AudioObjectRef(
            provider=self.provider_name,
            object_key=object_key,
            url=self.get_audio_url(object_key),
        )

    def download_audio(self, object_key: str, target_path: Path) -> Path:
        client = self._get_client()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(self.bucket, object_key, str(target_path))
        return target_path

    def delete_audio(self, object_key: str) -> None:
        client = self._get_client()
        client.delete_object(Bucket=self.bucket, Key=object_key)

    def get_audio_url(self, object_key: str) -> str | None:
        if self.settings.audio_storage_public_base_url:
            return f"{self.settings.audio_storage_public_base_url}/{quote(object_key)}"
        client = self._get_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=max(int(self.settings.audio_storage_presign_seconds), 60),
        )


class AudioStorageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.default_provider_name = settings.audio_storage_provider
        self._providers: dict[str, _BaseAudioProvider] = {}

    def _get_provider(self, provider_name: str | None = None) -> _BaseAudioProvider:
        name = (provider_name or self.default_provider_name or "local").strip().lower()
        provider = self._providers.get(name)
        if provider is not None:
            return provider
        if name == "local":
            provider = _LocalAudioProvider(self.settings)
        elif name == "s3":
            provider = _S3AudioProvider(self.settings)
        else:
            raise RuntimeError(f"不支持的音频存储 provider：{name}")
        self._providers[name] = provider
        return provider

    async def upload_audio(self, source_path: Path, *, bvid: str) -> AudioObjectRef:
        provider = self._get_provider()
        return await asyncio.to_thread(provider.upload_audio, source_path, bvid=bvid)

    async def download_audio(self, provider_name: str, object_key: str, target_path: Path) -> Path:
        provider = self._get_provider(provider_name)
        return await asyncio.to_thread(provider.download_audio, object_key, target_path)

    async def delete_audio(self, provider_name: str, object_key: str) -> None:
        provider = self._get_provider(provider_name)
        await asyncio.to_thread(provider.delete_audio, object_key)

    def get_audio_url(self, provider_name: str | None, object_key: str | None) -> str | None:
        if not provider_name or not object_key:
            return None
        provider = self._get_provider(provider_name)
        return provider.get_audio_url(object_key)


def create_audio_storage_service(settings: Settings) -> AudioStorageService:
    return AudioStorageService(settings)
