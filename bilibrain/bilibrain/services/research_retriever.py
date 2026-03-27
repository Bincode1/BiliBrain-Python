from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlparse

from bilibrain.core.config import Settings


def _domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return ""


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _coerce_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, list):
        if all(isinstance(item, dict) and item.get("type") == "text" for item in result):
            chunks: list[str] = []
            for item in result:
                text = _normalize_text(item.get("text"))
                if text:
                    chunks.append(text)
            return _coerce_payload("\n".join(chunks))
        return {"results": result}
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        text = result.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {"text": text}
        return parsed if isinstance(parsed, dict) else {"results": parsed}
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return _coerce_payload(content)
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = _normalize_text(item.get("text"))
                if text:
                    chunks.append(text)
        return _coerce_payload("\n".join(chunks))
    text = getattr(result, "text", None)
    if isinstance(text, str):
        return _coerce_payload(text)
    return {}


def _pick_tool(tools: list[Any], expected_name: str) -> Any | None:
    normalized_target = expected_name.strip().lower()
    normalized_variants = {
        normalized_target,
        normalized_target.replace("_", "-"),
        normalized_target.replace("-", "_"),
    }
    for tool in tools:
        name = str(getattr(tool, "name", "") or "").strip().lower()
        if name in normalized_variants:
            return tool
    for tool in tools:
        name = str(getattr(tool, "name", "") or "").strip().lower()
        if any(variant in name for variant in normalized_variants):
            return tool
    return None


@dataclass
class TavilyMCPRetrievalAgent:
    settings: Settings
    _tools: dict[str, Any] | None = field(default=None, init=False, repr=False)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.tavily_api_key)

    async def _ensure_tools(self) -> dict[str, Any]:
        if self._tools is not None:
            return self._tools

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except Exception as exc:
            raise RuntimeError("langchain-mcp-adapters is not installed.") from exc

        base_url = self.settings.tavily_mcp_url.rstrip("/")
        encoded_key = quote(self.settings.tavily_api_key, safe="")
        client = MultiServerMCPClient(
            {
                "tavily": {
                    "transport": "streamable_http",
                    "url": f"{base_url}/?tavilyApiKey={encoded_key}",
                }
            }
        )
        tools = await client.get_tools()
        search_tool = _pick_tool(tools, "tavily-search")
        extract_tool = _pick_tool(tools, "tavily-extract")
        if search_tool is None or extract_tool is None:
            raise RuntimeError("Tavily MCP tools are not available.")
        self._tools = {"search": search_tool, "extract": extract_tool}
        return self._tools

    async def retrieve(self, query: str, *, max_results: int = 6) -> list[dict[str, Any]]:
        if not self.enabled:
            return []

        tools = await self._ensure_tools()
        search_payload = _coerce_payload(
            await tools["search"].ainvoke(
                {
                    "query": str(query or "").strip(),
                    "max_results": max(int(max_results), 1),
                    "topic": "general",
                    "search_depth": "advanced",
                }
            )
        )
        raw_results = list(search_payload.get("results") or [])
        if not raw_results:
            return []

        candidates: list[dict[str, Any]] = []
        urls: list[str] = []
        seen_urls: set[str] = set()
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = _normalize_text(item.get("url"))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            urls.append(url)
            candidates.append(item)
            if len(urls) >= max(int(max_results), 1):
                break

        extract_payload = _coerce_payload(await tools["extract"].ainvoke({"urls": urls}))
        extracted_results = list(extract_payload.get("results") or [])
        extracted_by_url: dict[str, dict[str, Any]] = {}
        for item in extracted_results:
            if not isinstance(item, dict):
                continue
            url = _normalize_text(item.get("url"))
            if url:
                extracted_by_url[url] = item

        merged: list[dict[str, Any]] = []
        for item in candidates:
            url = _normalize_text(item.get("url"))
            extracted = extracted_by_url.get(url, {})
            title = _normalize_text(extracted.get("title") or item.get("title") or url)
            content = _normalize_text(
                extracted.get("raw_content")
                or extracted.get("content")
                or item.get("raw_content")
                or item.get("content")
                or item.get("snippet")
            )
            if not content:
                continue
            merged.append(
                {
                    "title": title,
                    "url": url,
                    "content": content,
                    "domain": _domain_from_url(url),
                    "provider": "tavily_mcp",
                    "score": item.get("score"),
                }
            )
        return merged
