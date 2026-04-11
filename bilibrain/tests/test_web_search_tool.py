import asyncio

import bilibrain.tools.web_search as web_search_module


def test_parse_bing_rss_results_extracts_title_url_and_snippet():
    xml_payload = """
    <?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Tokyo Travel Guide</title>
          <link>https://example.com/tokyo</link>
          <description>A compact 5-day Tokyo itinerary.</description>
        </item>
      </channel>
    </rss>
    """

    results = web_search_module._parse_bing_rss_results(xml_payload)

    assert len(results) == 1
    assert results[0]["title"] == "Tokyo Travel Guide"
    assert results[0]["url"] == "https://example.com/tokyo"
    assert results[0]["snippet"] == "A compact 5-day Tokyo itinerary."


def test_web_search_tool_returns_structured_payload(tmp_path, monkeypatch):
    async def fake_search(query: str, *, max_results: int = 5):
        return [
            {
                "rank": 1,
                "title": "Tokyo Travel Guide",
                "url": "https://example.com/tokyo",
                "snippet": f"query={query}, limit={max_results}",
                "provider": "bing_rss",
            }
        ]

    monkeypatch.setattr(web_search_module, "perform_web_search", fake_search)

    result = asyncio.run(
        web_search_module.web_search_tool(
            workspace_root=tmp_path,
            arguments={"query": "tokyo itinerary", "max_results": 3},
            workspace_id="ws-test",
            trace_id="trace-test",
        )
    )

    assert result.ok is True
    assert result.tool_name == "web_search"
    assert result.workspace_id == "ws-test"
    assert result.payload["query"] == "tokyo itinerary"
    assert result.payload["provider"] == "bing_rss"
    assert result.payload["result_count"] == 1
    assert result.payload["results"][0]["snippet"] == "query=tokyo itinerary, limit=3"
