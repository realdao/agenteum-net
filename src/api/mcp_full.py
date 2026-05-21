from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from src.resources.tool_guides import RESOURCE_URIS, resource_text_by_uri
from src.schemas import FetchRequest, SearchRequest


def create_mcp_server(*, search_service: Any, fetch_service: Any) -> FastMCP:
    mcp = FastMCP(
        "Agenteum Net",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    @mcp.tool()
    async def agenteum_search(
        query: str,
        max_result: int = 10,
        time_range: str | None = None,
        topic: str | None = None,
    ) -> dict:
        """Search the web through Tavily, Exa, and DuckDuckGo fallback providers."""
        request = SearchRequest(
            query=query,
            max_result=max_result,
            time_range=time_range,
            topic=topic,
        )
        response = await search_service.search(request)
        return response.model_dump(by_alias=True)

    @mcp.tool()
    async def agenteum_fetch(urls: list[str]) -> dict:
        """Fetch known URLs as Markdown. Returns one result item per URL."""
        request = FetchRequest(urls=urls)
        response = await fetch_service.fetch(request.normalized_urls())
        return response.model_dump()

    for uri in RESOURCE_URIS:
        _register_resource(mcp, uri)

    return mcp


def _register_resource(mcp: FastMCP, uri: str) -> None:
    @mcp.resource(uri)
    def read_resource() -> str:
        return resource_text_by_uri(uri)
