import pytest

from src.errors import ErrorType, ProviderError
from src.schemas import SearchRequest, SearchResult
from src.services.search_service import SearchService


class FakeSearchProvider:
    def __init__(self, name, result=None, error_type=None):
        self.name = name
        self.result = result
        self.error_type = error_type
        self.calls = 0

    async def search(self, request):
        self.calls += 1
        if self.error_type:
            raise ProviderError(
                error_type=self.error_type,
                provider=self.name,
                message=f"{self.name} failed",
            )
        return self.result


def result(source):
    return [
        SearchResult(
            title="Title",
            url=f"https://{source}.example",
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
