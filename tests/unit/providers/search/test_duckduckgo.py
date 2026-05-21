import pytest

from src.providers.search.duckduckgo import DuckDuckGoSearchProvider
from src.schemas import SearchRequest


class FakeDDGS:
    def text(self, query, max_results=None, timelimit=None):
        assert query == "mcp"
        assert max_results == 2
        return [
            {
                "title": "MCP",
                "href": "https://example.com/mcp",
                "body": "Duck result",
            }
        ]


@pytest.mark.asyncio
async def test_duckduckgo_success_maps_results():
    provider = DuckDuckGoSearchProvider(ddgs_factory=lambda: FakeDDGS())

    results = await provider.search(SearchRequest(query="mcp", max_result=2))

    assert results[0].url == "https://example.com/mcp"
    assert results[0].snippet == "Duck result"
    assert results[0].source == "duckduckgo"
