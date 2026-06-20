import pytest
from ddgs.exceptions import RatelimitException, TimeoutException

from src.errors import ErrorType, ProviderError
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


class SlowDDGS:
    def text(self, *args, **kwargs):
        import time

        time.sleep(0.2)
        return []


class RateLimitedDDGS:
    def text(self, *args, **kwargs):
        raise RatelimitException("rate limited")


class TimedOutDDGS:
    def text(self, *args, **kwargs):
        raise TimeoutException("timed out")


@pytest.mark.asyncio
async def test_duckduckgo_success_maps_results():
    provider = DuckDuckGoSearchProvider(ddgs_factory=lambda: FakeDDGS())

    results = await provider.search(SearchRequest(query="mcp", max_result=2))

    assert results[0].url == "https://example.com/mcp"
    assert results[0].snippet == "Duck result"
    assert results[0].source == "duckduckgo"


@pytest.mark.asyncio
async def test_duckduckgo_timeout_maps_to_timeout_error():
    provider = DuckDuckGoSearchProvider(ddgs_factory=lambda: SlowDDGS(), timeout=0.01)

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.TIMEOUT


@pytest.mark.asyncio
async def test_duckduckgo_rate_limit_exception_maps_to_rate_limited():
    provider = DuckDuckGoSearchProvider(ddgs_factory=lambda: RateLimitedDDGS())

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.RATE_LIMITED


@pytest.mark.asyncio
async def test_duckduckgo_library_timeout_exception_maps_to_timeout():
    provider = DuckDuckGoSearchProvider(ddgs_factory=lambda: TimedOutDDGS())

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.TIMEOUT
