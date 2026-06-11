import pytest

from src.errors import ErrorType, ProviderError
from src.schemas import FetchResult
from src.services.fetch_service import FetchService


class FakeFetchProvider:
    def __init__(self, name, result=None, error_type=None, http_status=None, exception=None):
        self.name = name
        self.result = result
        self.error_type = error_type
        self.http_status = http_status
        self.exception = exception
        self.calls = []

    async def fetch(self, url):
        self.calls.append(url)
        if self.exception:
            raise self.exception
        if self.error_type:
            raise ProviderError(
                error_type=self.error_type,
                provider=self.name,
                message=f"{self.name} failed",
                http_status=self.http_status,
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


@pytest.mark.asyncio
async def test_batch_preserves_jina_config_error_as_item_error():
    http = FakeFetchProvider("http")
    jina = FakeFetchProvider("jina", error_type=ErrorType.CONFIG_ERROR)
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://example.com", "https://x.com/openai/status/1"])

    assert [result.status for result in response.results] == ["ok", "error"]
    assert response.results[0].url == "https://example.com"
    assert response.results[1].url == "https://x.com/openai/status/1"
    assert response.results[1].source == "jina"
    assert response.results[1].error.type == "config_error"


@pytest.mark.asyncio
async def test_direct_jina_unexpected_exception_returns_jina_item_error():
    http = FakeFetchProvider("http")
    jina = FakeFetchProvider("jina", exception=RuntimeError("boom"))
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://x.com/openai/status/1"])

    assert response.results[0].status == "error"
    assert response.results[0].source == "jina"
    assert response.results[0].error.provider == "jina"
    assert response.results[0].error.type == "provider_error"
    assert response.results[0].error.message == "boom"
    assert http.calls == []


@pytest.mark.asyncio
async def test_jina_fallback_unexpected_exception_returns_jina_item_error():
    http = FakeFetchProvider("http", error_type=ErrorType.BLOCKED)
    jina = FakeFetchProvider("jina", exception=RuntimeError("boom"))
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://example.com"])

    assert response.results[0].status == "error"
    assert response.results[0].source == "jina"
    assert response.results[0].error.provider == "jina"
    assert response.results[0].error.type == "provider_error"
    assert response.results[0].error.message == "boom"
    assert jina.calls == ["https://example.com"]


@pytest.mark.asyncio
async def test_http_404_invalid_response_returns_item_error_without_jina():
    http = FakeFetchProvider("http", error_type=ErrorType.INVALID_RESPONSE, http_status=404)
    jina = FakeFetchProvider("jina")
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://example.com/missing"])

    assert response.results[0].status == "error"
    assert response.results[0].source == "http"
    assert response.results[0].error.type == "invalid_response"
    assert response.results[0].error.http_status == 404
    assert jina.calls == []


@pytest.mark.asyncio
async def test_unexpected_fetch_exception_becomes_provider_error_item():
    http = FakeFetchProvider("http", exception=RuntimeError("boom"))
    jina = FakeFetchProvider("jina")
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://example.com"])

    assert response.results[0].status == "error"
    assert response.results[0].source == "http"
    assert response.results[0].error.type == "provider_error"
    assert response.results[0].error.message == "boom"
    assert jina.calls == []
