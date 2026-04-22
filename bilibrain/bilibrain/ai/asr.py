from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from inspect import isawaitable
from pathlib import Path
from time import perf_counter
from typing import Any

from bilibrain.ai.audio_chunking import (
    SILENCE_END_RE,
    SILENCE_START_RE,
    plan_silence_aligned_ranges,
    trim_repeated_prefix,
)
from bilibrain.ai.qwen_asr import QwenAsrClient
from bilibrain.core.config import Settings

logger = logging.getLogger(__name__)


class AsrClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = QwenAsrClient(settings)

    def ensure_configured(self) -> None:
        self._client.ensure_configured()

    def model_label(self) -> str:
        return self._client.model_label()

    async def transcribe_audio_file(self, audio_path: Path, *, on_progress=None) -> dict[str, Any]:
        self.ensure_configured()
        total_started = perf_counter()
        with tempfile.TemporaryDirectory(prefix="bilibrain-asr-") as temp_dir:
            temp_path = Path(temp_dir)
            await self._emit_progress(
                on_progress,
                stage="chunking",
                message="正在分析静音并切分音频",
            )
            chunking_started = perf_counter()
            chunk_specs = await asyncio.to_thread(self._chunk_audio, audio_path, temp_path)
            if not chunk_specs:
                raise RuntimeError("ffmpeg produced no audio chunks")
            chunking_elapsed = perf_counter() - chunking_started
            logger.info(
                "ASR chunk preparation completed for %s: %s chunks in %.2fs",
                audio_path.name,
                len(chunk_specs),
                chunking_elapsed,
            )

            chunk_count = len(chunk_specs)
            chunk_concurrency = max(int(getattr(self.settings, "asr_chunk_concurrency", 2) or 2), 1)
            await self._emit_progress(
                on_progress,
                stage="transcribing",
                message=f"正在转写音频块 0/{chunk_count}",
                total_chunks=chunk_count,
                completed_chunks=0,
            )
            transcribe_started = perf_counter()
            raw_texts = await self._transcribe_chunks(
                chunk_specs,
                audio_label=audio_path.name,
                concurrency=chunk_concurrency,
                on_progress=on_progress,
            )
            transcribe_elapsed = perf_counter() - transcribe_started
            logger.info(
                "ASR transcription completed for %s: %s chunks in %.2fs with concurrency=%s",
                audio_path.name,
                chunk_count,
                transcribe_elapsed,
                chunk_concurrency,
            )

            assembly_started = perf_counter()
            segments = self._build_segments_from_chunks(chunk_specs, raw_texts)
            assembly_elapsed = perf_counter() - assembly_started
            logger.info(
                "ASR transcript assembly completed for %s: %s segments in %.2fs",
                audio_path.name,
                len(segments),
                assembly_elapsed,
            )

        transcript = "\n\n".join(segment["content"] for segment in segments if segment["content"])
        total_elapsed = perf_counter() - total_started
        logger.info(
            "ASR pipeline completed for %s: %s chunks, %s segments, %.2fs total",
            audio_path.name,
            len(chunk_specs),
            len(segments),
            total_elapsed,
        )
        return {
            "model": self._client.model_label(),
            "chunk_target_seconds": self.settings.asr_target_chunk_seconds,
            "chunk_max_seconds": self.settings.asr_chunk_seconds,
            "chunk_overlap_seconds": self.settings.asr_chunk_overlap_seconds,
            "segment_count": len(segments),
            "segments": segments,
            "text": transcript.strip(),
        }

    async def _transcribe_chunks(
        self,
        chunk_specs: list[dict[str, Any]],
        *,
        audio_label: str,
        concurrency: int,
        on_progress=None,
    ) -> list[str]:
        semaphore = asyncio.Semaphore(max(int(concurrency), 1))
        results: list[str] = [""] * len(chunk_specs)
        completed = 0

        async def _run_one(index: int, chunk_spec: dict[str, Any]) -> tuple[int, str]:
            async with semaphore:
                chunk_started = perf_counter()
                logger.info(
                    "ASR chunk started for %s: %s/%s (%s)",
                    audio_label,
                    index + 1,
                    len(chunk_specs),
                    chunk_spec["path"].name,
                )
                text = (await self._transcribe_file(chunk_spec["path"])).strip()
                chunk_elapsed = perf_counter() - chunk_started
                logger.info(
                    "ASR chunk completed for %s: %s/%s in %.2fs",
                    audio_label,
                    index + 1,
                    len(chunk_specs),
                    chunk_elapsed,
                )
                return index, text

        tasks = [asyncio.create_task(_run_one(index, chunk_spec)) for index, chunk_spec in enumerate(chunk_specs)]
        try:
            for task in asyncio.as_completed(tasks):
                index, text = await task
                results[index] = text
                completed += 1
                await self._emit_progress(
                    on_progress,
                    stage="transcribing",
                    message=f"正在转写音频块 {completed}/{len(chunk_specs)}",
                    total_chunks=len(chunk_specs),
                    completed_chunks=completed,
                    current_chunk=index + 1,
                )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        return results

    async def _transcribe_file(self, audio_path: Path) -> str:
        return await self._client.transcribe(audio_path)

    def _build_segments_from_chunks(
        self,
        chunk_specs: list[dict[str, Any]],
        raw_texts: list[str],
    ) -> list[dict[str, Any]]:
        segments = []
        previous_text = ""
        for index, (chunk_spec, raw_text) in enumerate(zip(chunk_specs, raw_texts, strict=False)):
            text = str(raw_text or "").strip()
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
        return segments

    async def _emit_progress(self, callback, **payload: Any) -> None:
        if callback is None:
            return
        result = callback(payload)
        if isawaitable(result):
            await result

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
