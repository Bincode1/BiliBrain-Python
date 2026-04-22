from __future__ import annotations

from typing import Any

from bilibrain.core.config import Settings
from bilibrain.prompts import (
    build_memory_compact_messages,
    build_summary_full_messages,
    build_summary_reduce_document_messages,
    build_summary_reduce_messages,
    build_summary_window_messages,
)


class QwenClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        try:
            from langchain_qwq import ChatQwen
        except ModuleNotFoundError as exc:
            raise RuntimeError("langchain_qwq is not installed") from exc
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


    async def compact_conversation_memory(
        self,
        *,
        existing_memory_text: str | None = None,
        history_transcript: str,
    ) -> str:
        self.ensure_configured()
        messages = build_memory_compact_messages(
            existing_memory_text=existing_memory_text,
            history_transcript=history_transcript,
        )
        return await self._invoke_messages(messages)

    async def summarize_video(
        self,
        *,
        video_title: str,
        transcript_text: str,
    ) -> str:
        self.ensure_configured()
        messages = build_summary_full_messages(
            video_title=video_title,
            transcript_text=transcript_text,
        )
        return await self._invoke_messages(messages)

    async def summarize_video_window(
        self,
        *,
        video_title: str,
        transcript_text: str,
    ) -> str:
        self.ensure_configured()
        messages = build_summary_window_messages(
            video_title=video_title,
            transcript_text=transcript_text,
        )
        return await self._invoke_messages(messages)

    async def reduce_video_summaries(
        self,
        *,
        video_title: str,
        window_summaries: list[str],
    ) -> str:
        self.ensure_configured()
        messages = build_summary_reduce_messages(
            video_title=video_title,
            window_summaries=window_summaries,
        )
        return await self._invoke_messages(messages)

    async def reduce_summary_documents(
        self,
        *,
        query: str,
        documents: list[dict[str, Any]],
    ) -> str:
        self.ensure_configured()
        context = self._build_summary_context(documents)
        messages = build_summary_reduce_document_messages(
            query=query,
            summary_text=context,
        )
        return await self._invoke_messages(messages)

    async def _invoke_messages(self, messages: list[tuple[str, str]]) -> str:
        result = await self.model.ainvoke(messages)
        return str(getattr(result, "text", None) or result.content).strip()

    async def _stream_messages(self, messages: list[tuple[str, str]]):
        async for chunk in self.model.astream(messages):
            text = getattr(chunk, "text", None) or getattr(chunk, "content", None) or ""
            if text:
                yield text

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

    async def close(self) -> None:
        return None
