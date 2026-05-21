import pytest

from src.api.mcp_full import create_mcp_server
from src.resources.tool_guides import load_resource_text
from src.schemas import SearchResponse


def test_resource_markdown_files_load():
    assert "agenteum_search" in load_resource_text("search-guide.md")
    assert "agenteum_fetch" in load_resource_text("fetch-guide.md")
    assert "Tavily" in load_resource_text("providers-capabilities.md")


@pytest.mark.asyncio
async def test_mcp_server_can_be_created_with_fake_services():
    class FakeSearchService:
        async def search(self, request):
            return SearchResponse(query=request.query, results=[], source="duckduckgo", fallbacks=[])

    class FakeFetchService:
        async def fetch(self, urls):
            from src.schemas import FetchResponse

            return FetchResponse(results=[])

    mcp = create_mcp_server(search_service=FakeSearchService(), fetch_service=FakeFetchService())

    assert mcp.name == "Agenteum Net"
