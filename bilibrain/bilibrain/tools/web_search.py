from __future__ import annotations

from typing import Any
from xml.etree import ElementTree

import httpx

from bilibrain.tools.contracts import ToolCallResult, ToolCallTimer


SEARCH_ENDPOINT = "https://www.bing.com/search"
SEARCH_PROVIDER = "bing_rss"
DEFAULT_MAX_RESULTS = 5
MAX_ALLOWED_RESULTS = 10


def _normalize_whitespace(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _parse_bing_rss_results(xml_text: str) -> list[dict[str, str]]:
    payload = str(xml_text or "").strip()
    if not payload:
        return []

    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        return []

    results: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        title = _normalize_whitespace(item.findtext("title", default=""))
        url = _normalize_whitespace(item.findtext("link", default=""))
        snippet = _normalize_whitespace(item.findtext("description", default=""))
        if title and url:
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                }
            )
    return results


async def perform_web_search(query: str, *, max_results: int = DEFAULT_MAX_RESULTS) -> list[dict[str, str]]:
    normalized_query = _normalize_whitespace(query)
    if not normalized_query:
        raise RuntimeError("Search query cannot be empty.")

    async with httpx.AsyncClient(
        timeout=15.0,
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    ) as client:
        response = await client.get(
            SEARCH_ENDPOINT,
            params={
                "q": normalized_query,
                "format": "rss",
                "setlang": "zh-Hans",
            },
        )
        response.raise_for_status()

    parsed_results = _parse_bing_rss_results(response.text)
    deduped: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    limit = min(max(int(max_results), 1), MAX_ALLOWED_RESULTS)
    for item in parsed_results:
        url = _normalize_whitespace(item.get("url", ""))
        title = _normalize_whitespace(item.get("title", ""))
        if not title or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(
            {
                "rank": len(deduped) + 1,
                "title": title,
                "url": url,
                "snippet": _normalize_whitespace(item.get("snippet", "")),
                "provider": SEARCH_PROVIDER,
            }
        )
        if len(deduped) >= limit:
            break
    return deduped


async def web_search_tool(
    *,
    workspace_root,
    arguments: dict[str, Any],
    workspace_id: str = "_local",
    trace_id: str = "local-web-search",
) -> ToolCallResult:
    timer = ToolCallTimer()
    query = _normalize_whitespace(str(arguments.get("query") or ""))
    max_results = min(max(int(arguments.get("max_results") or DEFAULT_MAX_RESULTS), 1), MAX_ALLOWED_RESULTS)
    results = await perform_web_search(query, max_results=max_results)
    return ToolCallResult(
        ok=True,
        tool_name="web_search",
        workspace_id=workspace_id,
        trace_id=trace_id,
        payload={
            "query": query,
            "provider": SEARCH_PROVIDER,
            "max_results": max_results,
            "result_count": len(results),
            "results": results,
        },
        duration_ms=timer.elapsed_ms(),
    )
