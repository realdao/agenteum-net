import httpx
import pytest

from src.errors import ErrorType, ProviderError
from src.providers.fetch.jina import JinaFetchProvider


@pytest.mark.asyncio
async def test_jina_success_returns_markdown():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer key"
        assert str(request.url) == "https://r.jina.ai/https://example.com/"
        return httpx.Response(200, text="# Example")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = JinaFetchProvider(api_key="key", client=client)

    result = await provider.fetch("https://example.com/")

    assert result.source == "jina"
    assert result.content == "# Example"
    await client.aclose()


@pytest.mark.asyncio
async def test_jina_missing_key_raises_config_error():
    provider = JinaFetchProvider(api_key=None)

    with pytest.raises(ProviderError) as raised:
        await provider.fetch("https://example.com/")

    assert raised.value.error_type == ErrorType.CONFIG_ERROR


@pytest.mark.asyncio
async def test_jina_rate_limit_maps_to_rate_limited():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too many requests")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = JinaFetchProvider(api_key="key", client=client)

    with pytest.raises(ProviderError) as raised:
        await provider.fetch("https://example.com/")

    assert raised.value.error_type == ErrorType.RATE_LIMITED
    assert raised.value.http_status == 429
    await client.aclose()
