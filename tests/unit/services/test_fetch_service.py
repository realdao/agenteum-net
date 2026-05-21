import pytest

from src.errors import ErrorType, ProviderError
from src.schemas import FetchResult
from src.services.fetch_service import FetchService


class FakeFetchProvider:
    def __init__(self, name, result=None, error_type=None):
        self.name = name
        self.result = result
        self.error_type = error_type
        self.calls = []

    async def fetch(self, url):
        self.calls.append(url)
        if self.error_type:
            raise ProviderError(
                error_type=self.error_type,
                provider=self.name,
                message=f"{self.name} failed",
            )
        return self.result or FetchResult(
            url=url,
            final_url=url,
            content=f"# {self.name}",
            source=self.name,
            status="ok",
            error=None,
        )


@pytest.mark.asyncio
async def test_x_url_routes_directly_to_jina():
    http = FakeFetchProvider("http")
    jina = FakeFetchProvider("jina")
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://x.com/openai/status/1"])

    assert response.results[0].source == "jina"
    assert http.calls == []


@pytest.mark.asyncio
async def test_blocked_http_falls_back_to_jina():
    http = FakeFetchProvider("http", error_type=ErrorType.BLOCKED)
    jina = FakeFetchProvider("jina")
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://example.com"])

    assert response.results[0].source == "jina"
    assert jina.calls == ["https://example.com"]


@pytest.mark.asyncio
async def test_unsupported_content_returns_item_error_without_jina():
    http = FakeFetchProvider("http", error_type=ErrorType.UNSUPPORTED_CONTENT)
    jina = FakeFetchProvider("jina")
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://example.com/a.pdf"])

    assert response.results[0].status == "error"
    assert response.results[0].error.type == "unsupported_content"
    assert jina.calls == []
