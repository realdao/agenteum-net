import json

import httpx
import pytest

from src.errors import ErrorType, ProviderError
from src.providers.search.exa import ExaSearchProvider
from src.schemas import SearchRequest


@pytest.mark.asyncio
async def test_exa_success_maps_results():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["query"] == "mcp"
        assert body["numResults"] == 3
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "MCP",
                        "url": "https://example.com/mcp",
                        "text": "Protocol text",
                        "publishedDate": "2026-05-01",
                        "score": 0.7,
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ExaSearchProvider(api_key="key", client=client)

    results = await provider.search(SearchRequest(query="mcp", max_result=3))

    assert results[0].snippet == "Protocol text"
    assert results[0].source == "exa"
    await client.aclose()


@pytest.mark.asyncio
async def test_exa_budget_error_maps_to_quota_exhausted():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"tag": "NO_MORE_CREDITS", "message": "No credits"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ExaSearchProvider(api_key="key", client=client)

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.QUOTA_EXHAUSTED
    await client.aclose()


@pytest.mark.asyncio
async def test_exa_invalid_key_maps_to_auth_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"tag": "INVALID_API_KEY"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ExaSearchProvider(api_key="key", client=client)

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.AUTH_ERROR
    await client.aclose()
