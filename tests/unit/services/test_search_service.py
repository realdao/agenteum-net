import asyncio

import pytest

from src.errors import ErrorType, ProviderError
from src.schemas import SearchRequest, SearchResult
from src.services.search_service import SearchService


class FakeSearchProvider:
    def __init__(self, name, result=None, error_type=None, delay=0.0):
        self.name = name
        self.result = result
        self.error_type = error_type
        self.delay = delay
        self.calls = 0

    async def search(self, request):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error_type:
            raise ProviderError(
                error_type=self.error_type,
                provider=self.name,
                message=f"{self.name} failed",
            )
        return self.result


def result(source, *, url=None, title="Title"):
    return [
        SearchResult(
            title=title,
            url=url or f"https://{source}.example",
            snippet=None,
            published_at=None,
            source=source,
            score=None,
        )
    ]


@pytest.mark.asyncio
async def test_tavily_success_stops_chain():
    tavily = FakeSearchProvider("tavily", result("tavily"))
    exa = FakeSearchProvider("exa", result("exa"))
    duckduckgo = FakeSearchProvider("duckduckgo", result("duckduckgo"))
    service = SearchService([tavily, exa, duckduckgo])

    response = await service.search(SearchRequest(query="mcp"))

    assert response.source == "tavily"
    assert exa.calls == 0
    assert duckduckgo.calls == 0


@pytest.mark.asyncio
async def test_quota_exhausted_falls_back_to_exa():
    tavily = FakeSearchProvider("tavily", error_type=ErrorType.QUOTA_EXHAUSTED)
    exa = FakeSearchProvider("exa", result("exa"))
    duckduckgo = FakeSearchProvider("duckduckgo", result("duckduckgo"))
    service = SearchService([tavily, exa, duckduckgo])

    response = await service.search(SearchRequest(query="mcp"))

    assert response.source == "exa"
    assert response.fallbacks[0].from_provider == "tavily"
    assert response.fallbacks[0].to_provider == "exa"
    assert response.fallbacks[0].reason == "quota_exhausted"


@pytest.mark.asyncio
async def test_auth_error_stops_chain():
    tavily = FakeSearchProvider("tavily", error_type=ErrorType.AUTH_ERROR)
    exa = FakeSearchProvider("exa", result("exa"))
    service = SearchService([tavily, exa])

    with pytest.raises(ProviderError) as raised:
        await service.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.AUTH_ERROR
    assert exa.calls == 0


@pytest.mark.asyncio
async def test_parallel_search_runs_selected_providers_and_deduplicates_urls():
    tavily = FakeSearchProvider(
        "tavily",
        [
            *result("tavily", url="https://example.com/a", title="Tavily A"),
            *result("tavily", url="https://example.com/shared", title="Tavily Shared"),
        ],
        delay=0.05,
    )
    exa = FakeSearchProvider(
        "exa",
        [
            *result("exa", url="https://example.com/shared", title="Exa Shared"),
            *result("exa", url="https://example.com/b", title="Exa B"),
        ],
    )
    duckduckgo = FakeSearchProvider("duckduckgo", result("duckduckgo"))
    service = SearchService([tavily, exa, duckduckgo])

    response = await service.parallel_search(
        SearchRequest(query="mcp"),
        provider_names=["tavily", "exa"],
    )

    assert tavily.calls == 1
    assert exa.calls == 1
    assert duckduckgo.calls == 0
    assert response.sources == ["tavily", "exa"]
    assert [item.url for item in response.results] == [
        "https://example.com/a",
        "https://example.com/shared",
        "https://example.com/b",
    ]
    assert response.results[1].title == "Tavily Shared"
    assert response.errors == []


@pytest.mark.asyncio
async def test_parallel_search_uses_all_providers_when_provider_names_empty():
    tavily = FakeSearchProvider("tavily", result("tavily"))
    exa = FakeSearchProvider("exa", result("exa"))
    service = SearchService([tavily, exa])

    response = await service.parallel_search(SearchRequest(query="mcp"), provider_names=[])

    assert tavily.calls == 1
    assert exa.calls == 1
    assert response.sources == ["tavily", "exa"]


@pytest.mark.asyncio
async def test_parallel_search_deduplicates_requested_provider_names_preserving_order():
    tavily = FakeSearchProvider("tavily", result("tavily"))
    exa = FakeSearchProvider("exa", result("exa"))
    service = SearchService([tavily, exa])

    response = await service.parallel_search(
        SearchRequest(query="mcp"),
        provider_names=["exa", "tavily", "exa", "tavily"],
    )

    assert exa.calls == 1
    assert tavily.calls == 1
    assert response.sources == ["exa", "tavily"]


@pytest.mark.asyncio
async def test_parallel_search_returns_partial_errors_when_some_providers_fail():
    tavily = FakeSearchProvider("tavily", error_type=ErrorType.RATE_LIMITED)
    exa = FakeSearchProvider("exa", result("exa"))
    service = SearchService([tavily, exa])

    response = await service.parallel_search(SearchRequest(query="mcp"))

    assert response.sources == ["exa"]
    assert [item.source for item in response.results] == ["exa"]
    assert len(response.errors) == 1
    assert response.errors[0].provider == "tavily"
    assert response.errors[0].type == "rate_limited"


@pytest.mark.asyncio
async def test_parallel_search_raises_when_all_selected_providers_fail():
    tavily = FakeSearchProvider("tavily", error_type=ErrorType.RATE_LIMITED)
    exa = FakeSearchProvider("exa", error_type=ErrorType.AUTH_ERROR)
    service = SearchService([tavily, exa])

    with pytest.raises(ProviderError) as raised:
        await service.parallel_search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.AUTH_ERROR


@pytest.mark.asyncio
async def test_parallel_search_rejects_unknown_provider_names():
    service = SearchService([FakeSearchProvider("tavily", result("tavily"))])

    with pytest.raises(ProviderError) as raised:
        await service.parallel_search(SearchRequest(query="mcp"), provider_names=["unknown"])

    assert raised.value.error_type == ErrorType.INVALID_REQUEST
