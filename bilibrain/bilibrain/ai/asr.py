from __future__ import annotations

import asyncio
import base64
import mimetypes
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_qwq import ChatQwen

from bilibrain.ai.audio_chunking import (
    SILENCE_END_RE,
    SILENCE_START_RE,
    plan_silence_aligned_ranges,
    trim_repeated_prefix,
)
from bilibrain.core.config import Settings


class AsrClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = ChatQwen(
            model=settings.asr_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            temperature=0,
        )

    def ensure_configured(self) -> None:
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY not set")
        if not self.settings.asr_model:
            raise RuntimeError("ASR_MODEL not set")

    async def transcribe_audio_file(self, audio_path: Path) -> dict[str, Any]:
        self.ensure_configured()
        with tempfile.TemporaryDirectory(prefix="bilibrain-asr-") as temp_dir:
            temp_path = Path(temp_dir)
            chunk_specs = await asyncio.to_thread(self._chunk_audio, audio_path, temp_path)
            if not chunk_specs:
                raise RuntimeError("ffmpeg produced no audio chunks")

            segments = []
            previous_text = ""
            for index, chunk_spec in enumerate(chunk_specs):
                text = (await self.transcribe_file(chunk_spec["path"])).strip()
                if chunk_spec["clip_start_seconds"] < chunk_spec["start_seconds"]:
                    text = trim_repeated_prefix(previous_text, text)
                start_seconds = float(chunk_spec["start_seconds"])
                end_seconds = float(chunk_spec["end_seconds"])
                segments.append(
                    {
                        "index": index,
                        "start_seconds": round(start_seconds, 3),
                        "end_seconds": round(end_seconds, 3),
                        "content": text.strip(),
                    }
                )
                if text:
                    previous_text = text.strip()

        transcript = "\n\n".join(segment["content"] for segment in segments if segment["content"])
        return {
            "model": self.settings.asr_model,
            "chunk_target_seconds": self.settings.asr_target_chunk_seconds,
            "chunk_max_seconds": self.settings.asr_chunk_seconds,
            "chunk_overlap_seconds": self.settings.asr_chunk_overlap_seconds,
            "segment_count": len(segments),
            "segments": segments,
            "text": transcript.strip(),
        }

    async def transcribe_file(self, audio_path: Path) -> str:
        payload = self._build_audio_data_url(audio_path)
        message = HumanMessage(
            content=[
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": payload,
                    },
                }
            ]
        )
        result = await self.model.ainvoke(
            [message],
            extra_body={
                "asr_options": {
                    "language": self.settings.asr_language,
                    "enable_itn": True,
                }
            },
        )
        return str(result.content).strip()

    def _build_audio_data_url(self, audio_path: Path) -> str:
        mime_type, _ = mimetypes.guess_type(audio_path.name)
        mime_type = mime_type or "audio/mpeg"
        payload = base64.b64encode(audio_path.read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{payload}"

    def _chunk_audio(self, audio_path: Path, output_dir: Path) -> list[dict[str, Any]]:
        total_duration = self._probe_duration(audio_path)
        if total_duration <= 0:
            return []

        silence_points = self._detect_silence_points(audio_path, total_duration)
        logical_ranges = plan_silence_aligned_ranges(
            duration_seconds=total_duration,
            silence_points=silence_points,
            target_seconds=self.settings.asr_target_chunk_seconds,
            max_seconds=self.settings.asr_chunk_seconds,
        )

        overlap_seconds = max(float(self.settings.asr_chunk_overlap_seconds), 0.0)
        chunk_specs: list[dict[str, Any]] = []
        for index, (start_seconds, end_seconds) in enumerate(logical_ranges):
            clip_start_seconds = max(0.0, start_seconds - overlap_seconds) if index > 0 else start_seconds
            clip_end_seconds = end_seconds
            output_path = output_dir / f"chunk-{index:03d}.mp3"
            self._extract_audio_range(
                audio_path=audio_path,
                output_path=output_path,
                start_seconds=clip_start_seconds,
                end_seconds=clip_end_seconds,
            )
            chunk_specs.append(
                {
                    "path": output_path,
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                    "clip_start_seconds": clip_start_seconds,
                    "clip_end_seconds": clip_end_seconds,
                }
            )
        return chunk_specs

    def _detect_silence_points(self, audio_path: Path, total_duration: float) -> list[float]:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(audio_path),
            "-af",
            f"silencedetect=noise={self.settings.asr_silence_noise_db}dB:d={self.settings.asr_silence_min_seconds}",
            "-f",
            "null",
            "-",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(f"ffmpeg failed: {stderr or 'unknown error'}")

        silence_starts: list[float] = []
        cut_points: list[float] = []
        for line in (result.stderr or "").splitlines():
            start_match = SILENCE_START_RE.search(line)
            if start_match:
                silence_starts.append(float(start_match.group(1)))
                continue
            end_match = SILENCE_END_RE.search(line)
            if end_match and silence_starts:
                silence_end = float(end_match.group(1))
                silence_start = silence_starts.pop(0)
                midpoint = (silence_start + silence_end) / 2
                if 0 < midpoint < total_duration:
                    cut_points.append(midpoint)

        return cut_points

    def _extract_audio_range(
        self,
        *,
        audio_path: Path,
        output_path: Path,
        start_seconds: float,
        end_seconds: float,
    ) -> None:
        duration = max(float(end_seconds) - float(start_seconds), 0.1)
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{float(start_seconds):.3f}",
            "-i",
            str(audio_path),
            "-t",
            f"{duration:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "48k",
            str(output_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(f"ffmpeg failed: {stderr or 'unknown error'}")

    def _probe_duration(self, audio_path: Path) -> float:
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            return float(self.settings.asr_chunk_seconds)
        try:
            return float((result.stdout or "").strip())
        except ValueError:
            return float(self.settings.asr_chunk_seconds)

    async def close(self) -> None:
        return None
