from __future__ import annotations

import asyncio
import base64
import mimetypes
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_ollama import OllamaEmbeddings
from langchain_qwq import ChatQwen

from bilibrain.core.config import Settings
from bilibrain.services.common import seconds_to_timestamp


SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")


def trim_repeated_prefix(previous_text: str, current_text: str, *, min_match_chars: int = 8) -> str:
    previous = str(previous_text or "").strip()
    current = str(current_text or "").strip()
    if not previous or not current:
        return current

    max_match = min(len(previous), len(current), 80)
    for size in range(max_match, min_match_chars - 1, -1):
        if previous[-size:] == current[:size]:
            return current[size:].lstrip(" ，,。！？!?；;：:")
    return current


def plan_silence_aligned_ranges(
    *,
    duration_seconds: float,
    silence_points: list[float],
    target_seconds: float,
    max_seconds: float,
) -> list[tuple[float, float]]:
    total_duration = max(float(duration_seconds), 0.0)
    if total_duration <= 0:
        return []

    safe_target = max(min(float(target_seconds), float(max_seconds)), 1.0)
    safe_max = max(float(max_seconds), safe_target)
    min_chunk = min(max(safe_target * 0.5, 20.0), safe_target)
    cut_points = sorted(
        {
            round(point, 3)
            for point in silence_points
            if min_chunk <= float(point) < total_duration
        }
    )

    ranges: list[tuple[float, float]] = []
    cursor = 0.0
    while cursor < total_duration:
        hard_end = min(cursor + safe_max, total_duration)
        if total_duration - cursor <= safe_max:
            end = total_duration
        else:
            preferred_end = min(cursor + safe_target, total_duration)
            candidates = [
                point
                for point in cut_points
                if cursor + min_chunk <= point <= hard_end
            ]
            if candidates:
                end = min(candidates, key=lambda point: (abs(point - preferred_end), point))
            else:
                end = hard_end

        if end <= cursor:
            end = min(cursor + safe_max, total_duration)
        ranges.append((round(cursor, 3), round(end, 3)))
        cursor = end

    return ranges


class EmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OllamaEmbeddings(
            model=settings.embedding_model,
            base_url=settings.ollama_base_url,
        )

    def ensure_configured(self) -> None:
        if not self.settings.embedding_model:
            raise RuntimeError("EMBEDDING_MODEL not set")

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.ensure_configured()
        embeddings = await asyncio.to_thread(self.client.embed_documents, texts)
        if not isinstance(embeddings, list):
            raise RuntimeError("Ollama embedding returned invalid format")
        return embeddings

    async def close(self) -> None:
        return None


class QwenClient:
    SYSTEM_PROMPT = "你是 BiliBrain，只能根据给定资料回答，不要补充资料外的知识。"
    SUMMARY_SYSTEM_PROMPT = "你是 BiliBrain 的摘要助手，只能依据给定文本压缩信息，不要补充外部知识。"
    MAX_HISTORY_MESSAGES = 8

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = ChatQwen(
            model=settings.llm_model,
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            temperature=0,
            streaming=True,
            enable_thinking=False,
        )

    def ensure_configured(self) -> None:
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY not set")

    def _build_messages(
        self,
        query: str,
        context: str,
        history: list[dict[str, Any]] | None = None,
        *,
        citations_required: bool = True,
    ) -> list[tuple[str, str]]:
        messages: list[tuple[str, str]] = [("system", self.SYSTEM_PROMPT)]
        for item in self._normalize_history(history):
            role = "human" if item["role"] == "user" else "ai"
            messages.append((role, item["content"]))
        rules = [
            "1. 只使用资料里的信息，不要补充外部知识。",
            "2. 如果资料不足以回答，就直接说明“你的收藏内容里没有足够信息回答这个问题”。",
            "3. 如果历史对话与当前资料冲突，以当前资料为准。",
            "4. 回答用中文，简洁直接。",
        ]
        if citations_required:
            rules.extend(
                [
                    "5. 关键结论或每个自然段结尾请附上资料编号，格式必须是【1】或【1】【3】。",
                    "6. 编号只能使用资料里已有的编号；如果某句无法从资料直接得到，就不要写那句。",
                ]
            )
        messages.append(
            (
                "human",
                "\n".join(
                    [
                        "规则：",
                        *rules,
                        "",
                        f"用户问题：{query}",
                        "",
                        "资料：",
                        context,
                    ]
                ),
            )
        )
        return messages

    async def answer(
        self,
        query: str,
        matches: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
    ) -> str:
        self.ensure_configured()
        context = self._build_context(matches)
        messages = self._build_messages(query, context, history)
        return await self._invoke_messages(messages)

    async def stream_answer(
        self,
        query: str,
        matches: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
    ):
        self.ensure_configured()
        context = self._build_context(matches)
        messages = self._build_messages(query, context, history)
        async for text in self._stream_messages(messages):
            yield text

    async def answer_from_summary_documents(
        self,
        query: str,
        documents: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
    ) -> str:
        self.ensure_configured()
        context = self._build_summary_context(documents)
        messages = self._build_messages(query, context, history, citations_required=False)
        return await self._invoke_messages(messages)

    async def stream_answer_from_summary_documents(
        self,
        query: str,
        documents: list[dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
    ):
        self.ensure_configured()
        context = self._build_summary_context(documents)
        messages = self._build_messages(query, context, history, citations_required=False)
        async for text in self._stream_messages(messages):
            yield text

    async def summarize_video(
        self,
        *,
        video_title: str,
        transcript_text: str,
    ) -> str:
        self.ensure_configured()
        messages = [
            ("system", self.SUMMARY_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"视频标题：{video_title}",
                        "",
                        "任务：请根据以下视频转写内容输出一份完整摘要。",
                        "要求：",
                        "1. 只依据给定内容，不补充外部知识。",
                        "2. 回答用中文。",
                        "3. 输出结构固定为：一句话概括、核心要点、详细梳理。",
                        "4. 核心要点控制在 4 到 8 条，覆盖主要主题、方法、结论和步骤。",
                        "5. 避免重复和空话，不要写“视频提到”等低信息密度表述。",
                        "",
                        "转写内容：",
                        transcript_text,
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def summarize_video_window(
        self,
        *,
        video_title: str,
        transcript_text: str,
    ) -> str:
        self.ensure_configured()
        messages = [
            ("system", self.SUMMARY_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"视频标题：{video_title}",
                        "",
                        "任务：请把下面这段视频转写压缩成局部摘要。",
                        "要求：",
                        "1. 只依据给定内容，不补充外部知识。",
                        "2. 回答用中文。",
                        "3. 输出 3 到 6 条要点。",
                        "4. 保留重要概念、步骤、结论和例子线索。",
                        "5. 不要写标题，不要写额外解释。",
                        "",
                        "转写内容：",
                        transcript_text,
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def reduce_video_summaries(
        self,
        *,
        video_title: str,
        window_summaries: list[str],
    ) -> str:
        self.ensure_configured()
        payload = "\n\n".join(
            f"[局部摘要 {index}]\n{summary.strip()}"
            for index, summary in enumerate(window_summaries, start=1)
            if str(summary or "").strip()
        )
        messages = [
            ("system", self.SUMMARY_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"视频标题：{video_title}",
                        "",
                        "任务：以下是同一个视频多个片段的局部摘要，请合并成一份最终摘要。",
                        "要求：",
                        "1. 只依据局部摘要内容，不补充外部知识。",
                        "2. 回答用中文。",
                        "3. 输出结构固定为：一句话概括、核心要点、详细梳理。",
                        "4. 核心要点控制在 4 到 8 条，尽量覆盖整个视频主要主题。",
                        "5. 去掉重复信息，保留关键结论、方法、步骤和注意点。",
                        "",
                        "局部摘要：",
                        payload,
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def reduce_summary_documents(
        self,
        *,
        query: str,
        documents: list[dict[str, Any]],
    ) -> str:
        self.ensure_configured()
        context = self._build_summary_context(documents)
        messages = [
            ("system", self.SUMMARY_SYSTEM_PROMPT),
            (
                "human",
                "\n".join(
                    [
                        f"用户问题：{query}",
                        "",
                        "任务：以下是同一范围内多个视频的摘要，请先做一轮中间压缩，供后续总汇总使用。",
                        "要求：",
                        "1. 只依据给定摘要，不补充外部知识。",
                        "2. 回答用中文。",
                        "3. 输出 4 到 8 条高信息密度要点。",
                        "4. 优先保留共性主题、代表观点和明显差异。",
                        "5. 不要写空话，不要附加编号解释。",
                        "",
                        "视频摘要：",
                        context,
                    ]
                ),
            ),
        ]
        return await self._invoke_messages(messages)

    async def _invoke_messages(self, messages: list[tuple[str, str]]) -> str:
        result = await self.model.ainvoke(messages)
        return str(getattr(result, "text", None) or result.content).strip()

    async def _stream_messages(self, messages: list[tuple[str, str]]):
        async for chunk in self.model.astream(messages):
            text = getattr(chunk, "text", None) or ""
            if text:
                yield text

    def _build_context(self, matches: list[dict[str, Any]]) -> str:
        lines = []
        for idx, item in enumerate(matches, start=1):
            lines.append(
                f"[{idx}] {item['video_title']} | {item.get('up_name', 'Unknown')} @ {seconds_to_timestamp(item['start_seconds'])}: {item['content']}"
            )
        return "\n".join(lines)

    def _build_summary_context(self, documents: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for idx, item in enumerate(documents, start=1):
            lines.append(
                "\n".join(
                    [
                        f"[{idx}] {item.get('video_title', '未知视频')} | {item.get('up_name', 'Unknown')}",
                        str(item.get("summary_text") or "").strip(),
                    ]
                )
            )
        return "\n\n".join(lines)

    def _normalize_history(self, history: list[dict[str, Any]] | None) -> list[dict[str, str]]:
        if not history:
            return []

        normalized: list[dict[str, str]] = []
        for item in history:
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            normalized.append({"role": role, "content": content})
        if len(normalized) <= self.MAX_HISTORY_MESSAGES:
            return normalized
        return normalized[-self.MAX_HISTORY_MESSAGES :]

    async def close(self) -> None:
        return None


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
