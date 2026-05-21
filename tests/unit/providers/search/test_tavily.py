import json

import httpx
import pytest

from src.errors import ErrorType, ProviderError
from src.providers.search.tavily import TavilySearchProvider
from src.schemas import SearchRequest


@pytest.mark.asyncio
async def test_tavily_success_maps_results():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["query"] == "mcp"
        assert body["max_results"] == 5
        assert body["topic"] == "news"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "MCP",
                        "url": "https://example.com/mcp",
                        "content": "Model Context Protocol",
                        "score": 0.8,
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TavilySearchProvider(api_key="key", client=client)

    results = await provider.search(SearchRequest(query="mcp", max_result=5, topic="news"))

    assert results[0].title == "MCP"
    assert results[0].source == "tavily"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (400, ErrorType.INVALID_REQUEST),
        (401, ErrorType.AUTH_ERROR),
        (403, ErrorType.AUTH_ERROR),
        (429, ErrorType.RATE_LIMITED),
        (432, ErrorType.QUOTA_EXHAUSTED),
        (433, ErrorType.QUOTA_EXHAUSTED),
        (500, ErrorType.PROVIDER_5XX),
    ],
)
async def test_tavily_error_mapping(status_code, error_type):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "provider error"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TavilySearchProvider(api_key="key", client=client)

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == error_type
    await client.aclose()


@pytest.mark.asyncio
async def test_tavily_missing_key_raises_config_error():
    provider = TavilySearchProvider(api_key=None)

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.CONFIG_ERROR
