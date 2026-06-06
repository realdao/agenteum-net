import pytest

from src.api.mcp_full import create_mcp_server
from src.resources.tool_guides import load_resource_text
from src.schemas import FetchResponse, FetchResult, ParallelSearchResponse, SearchResponse


def test_resource_markdown_files_load():
    assert "search" in load_resource_text("search-guide.md")
    assert "fetch" in load_resource_text("fetch-guide.md")
    assert "Tavily" in load_resource_text("providers-capabilities.md")


@pytest.mark.asyncio
async def test_mcp_server_can_be_created_with_fake_services():
    class FakeSearchService:
        async def search(self, request):
            return SearchResponse(
                query=request.query,
                results=[],
                source="duckduckgo",
                fallbacks=[],
            )

        async def parallel_search(self, request, provider_names=None):
            return ParallelSearchResponse(
                query=request.query,
                results=[],
                sources=provider_names or ["duckduckgo"],
                errors=[],
            )

    class FakeFetchService:
        async def fetch(self, urls):
            from src.schemas import FetchResponse

            return FetchResponse(results=[])

    mcp = create_mcp_server(search_service=FakeSearchService(), fetch_service=FakeFetchService())

    assert mcp.name == "Agenteum Net"


@pytest.mark.asyncio
async def test_mcp_server_registers_short_tool_names_only():
    class FakeSearchService:
        async def search(self, request):
            return SearchResponse(
                query=request.query,
                results=[],
                source="duckduckgo",
                fallbacks=[],
            )

        async def parallel_search(self, request, provider_names=None):
            return ParallelSearchResponse(
                query=request.query,
                results=[],
                sources=provider_names or ["duckduckgo"],
                errors=[],
            )

    class FakeFetchService:
        async def fetch(self, urls):
            return FetchResponse(results=[])

    mcp = create_mcp_server(search_service=FakeSearchService(), fetch_service=FakeFetchService())

    assert set(mcp._tool_manager._tools) == {"search", "parallel_search", "fetch"}


@pytest.mark.asyncio
async def test_search_tool_logs_function_parameters_and_debug_result(caplog):
    class FakeSearchService:
        async def search(self, request):
            return SearchResponse(
                query=request.query,
                results=[],
                source="duckduckgo",
                fallbacks=[],
            )

        async def parallel_search(self, request, provider_names=None):
            return ParallelSearchResponse(
                query=request.query,
                results=[],
                sources=provider_names or ["duckduckgo"],
                errors=[],
            )

    class FakeFetchService:
        async def fetch(self, urls):
            return FetchResponse(results=[])

    mcp = create_mcp_server(search_service=FakeSearchService(), fetch_service=FakeFetchService())

    with caplog.at_level("DEBUG", logger="agenteum_net"):
        result = await mcp._tool_manager.call_tool(
            "search",
            {"query": "mcp logging", "max_result": 3, "time_range": "week", "topic": "news"},
        )

    assert result == {
        "query": "mcp logging",
        "results": [],
        "source": "duckduckgo",
        "fallbacks": [],
    }
    assert "tool call" in caplog.text
    assert "tool result" in caplog.text
    assert any(
        record.levelname == "INFO"
        and record.function == "search"
        and record.params == {
            "query": "mcp logging",
            "max_result": 3,
            "time_range": "week",
            "topic": "news",
        }
        for record in caplog.records
    )
    assert any(
        record.levelname == "DEBUG"
        and record.function == "search"
        and record.result == result
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_fetch_tool_logs_function_parameters_and_debug_result(caplog):
    class FakeSearchService:
        async def search(self, request):
            return SearchResponse(
                query=request.query,
                results=[],
                source="duckduckgo",
                fallbacks=[],
            )

        async def parallel_search(self, request, provider_names=None):
            return ParallelSearchResponse(
                query=request.query,
                results=[],
                sources=provider_names or ["duckduckgo"],
                errors=[],
            )

    class FakeFetchService:
        async def fetch(self, urls):
            return FetchResponse(
                results=[
                    FetchResult(
                        url=urls[0],
                        final_url=urls[0],
                        content="Example",
                        source="http",
                        status="ok",
                    )
                ]
            )

    mcp = create_mcp_server(search_service=FakeSearchService(), fetch_service=FakeFetchService())

    with caplog.at_level("DEBUG", logger="agenteum_net"):
        result = await mcp._tool_manager.call_tool(
            "fetch",
            {"urls": ["https://example.com"]},
        )

    assert result == {
        "results": [
            {
                "url": "https://example.com/",
                "final_url": "https://example.com/",
                "content": "Example",
                "source": "http",
                "status": "ok",
                "error": None,
            }
        ]
    }
    assert any(
        record.levelname == "INFO"
        and record.function == "fetch"
        and record.params == {"urls": ["https://example.com"]}
        for record in caplog.records
    )
    assert any(
        record.levelname == "DEBUG"
        and record.function == "fetch"
        and record.result == result
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_parallel_search_tool_accepts_optional_providers_and_logs(caplog):
    class FakeSearchService:
        async def search(self, request):
            return SearchResponse(
                query=request.query,
                results=[],
                source="duckduckgo",
                fallbacks=[],
            )

        async def parallel_search(self, request, provider_names=None):
            return ParallelSearchResponse(
                query=request.query,
                results=[],
                sources=provider_names or ["tavily", "exa", "duckduckgo"],
                errors=[],
            )

    class FakeFetchService:
        async def fetch(self, urls):
            return FetchResponse(results=[])

    mcp = create_mcp_server(search_service=FakeSearchService(), fetch_service=FakeFetchService())

    with caplog.at_level("DEBUG", logger="agenteum_net"):
        result = await mcp._tool_manager.call_tool(
            "parallel_search",
            {
                "query": "mcp logging",
                "max_result": 3,
                "time_range": "week",
                "topic": "news",
                "providers": ["tavily", "exa"],
            },
        )

    assert result == {
        "query": "mcp logging",
        "results": [],
        "sources": ["tavily", "exa"],
        "errors": [],
    }
    assert any(
        record.levelname == "INFO"
        and record.function == "parallel_search"
        and record.params == {
            "query": "mcp logging",
            "max_result": 3,
            "time_range": "week",
            "topic": "news",
            "providers": ["tavily", "exa"],
        }
        for record in caplog.records
    )
    assert any(
        record.levelname == "DEBUG"
        and record.function == "parallel_search"
        and record.result == result
        for record in caplog.records
    )
