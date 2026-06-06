import pytest
from pydantic import ValidationError

from src.schemas import (
    FetchRequest,
    FetchResponse,
    FetchResult,
    ParallelSearchResponse,
    SearchProviderError,
    SearchRequest,
    SearchResponse,
    SearchResult,
)


def test_search_request_caps_max_result_at_twenty():
    request = SearchRequest(query="python mcp", max_result=20)

    assert request.max_result == 20


def test_search_request_rejects_too_many_results():
    with pytest.raises(ValidationError):
        SearchRequest(query="python mcp", max_result=21)


def test_search_response_serializes_unified_results():
    result = SearchResult(
        title="Example",
        url="https://example.com",
        snippet="Example snippet",
        published_at=None,
        source="tavily",
        score=0.9,
    )
    response = SearchResponse(query="example", results=[result], source="tavily", fallbacks=[])

    assert response.model_dump()["results"][0]["source"] == "tavily"


def test_parallel_search_response_serializes_sources_and_errors():
    result = SearchResult(
        title="Example",
        url="https://example.com",
        snippet="Example snippet",
        published_at=None,
        source="tavily",
        score=0.9,
    )
    response = ParallelSearchResponse(
        query="example",
        results=[result],
        sources=["tavily"],
        errors=[
            SearchProviderError(
                provider="exa",
                type="rate_limited",
                message="Exa failed",
            )
        ],
    )

    dumped = response.model_dump()

    assert dumped["sources"] == ["tavily"]
    assert dumped["errors"][0]["provider"] == "exa"


def test_fetch_request_rejects_more_than_ten_urls():
    with pytest.raises(ValidationError):
        FetchRequest(urls=[f"https://example.com/{index}" for index in range(11)])


def test_fetch_request_rejects_non_http_urls():
    with pytest.raises(ValidationError):
        FetchRequest(urls=["file:///tmp/example.html"])


def test_fetch_response_allows_item_level_error():
    item = FetchResult(
        url="https://blocked.example",
        final_url=None,
        content=None,
        source="http",
        status="error",
        error={"type": "blocked", "message": "Blocked page", "provider": "http"},
    )
    response = FetchResponse(results=[item])

    assert response.results[0].status == "error"
    assert response.results[0].error is not None
