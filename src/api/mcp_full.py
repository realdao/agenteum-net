from __future__ import annotations

import logging
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from src.resources.tool_guides import RESOURCE_URIS, resource_text_by_uri
from src.schemas import FetchRequest, SearchProviderName, SearchRequest, TimeRange

SearchLimit = Annotated[int, Field(ge=1, le=20)]
FetchUrls = Annotated[list[str], Field(min_length=1, max_length=10)]
ParallelProviders = list[SearchProviderName]


def create_mcp_server(
    *,
    search_service: Any,
    fetch_service: Any,
    allow_remote: bool = False,
) -> FastMCP:
    logger = logging.getLogger("agenteum_net")
    # FastMCP auto-enables localhost-only DNS-rebinding protection when host is
    # 127.0.0.1/localhost. That blocks remote clients reaching the service via a
    # domain name or public IP (the SDK rejects their Host header with 421).
    # When the operator explicitly opts into remote access via
    # AGENTEUM_ALLOW_REMOTE=true, disable that protection so external Host
    # headers are accepted. Authentication should be handled separately.
    transport_security = (
        TransportSecuritySettings(enable_dns_rebinding_protection=False)
        if allow_remote
        else None
    )
    mcp = FastMCP(
        "Agenteum Net",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=transport_security,
    )

    @mcp.tool()
    async def search(
        query: str,
        max_result: SearchLimit = 10,
        time_range: TimeRange | None = None,
        topic: str | None = None,
    ) -> dict:
        """Search the web through Tavily, Exa, and DuckDuckGo fallback providers."""
        params = {
            "query": query,
            "max_result": max_result,
            "time_range": time_range,
            "topic": topic,
        }
        logger.info(
            "tool call function=%s params=%s",
            "search",
            params,
            extra={"function": "search", "params": params},
        )
        request = SearchRequest(
            query=query,
            max_result=max_result,
            time_range=time_range,
            topic=topic,
        )
        response = await search_service.search(request)
        result = response.model_dump(by_alias=True)
        logger.debug(
            "tool result function=%s result=%s",
            "search",
            result,
            extra={"function": "search", "result": result},
        )
        return result

    @mcp.tool()
    async def parallel_search(
        query: str,
        max_result: SearchLimit = 10,
        time_range: TimeRange | None = None,
        topic: str | None = None,
        providers: ParallelProviders | None = None,
    ) -> dict:
        """Search selected providers in parallel, merge results, and deduplicate by URL."""
        params = {
            "query": query,
            "max_result": max_result,
            "time_range": time_range,
            "topic": topic,
            "providers": providers,
        }
        logger.info(
            "tool call function=%s params=%s",
            "parallel_search",
            params,
            extra={"function": "parallel_search", "params": params},
        )
        request = SearchRequest(
            query=query,
            max_result=max_result,
            time_range=time_range,
            topic=topic,
        )
        response = await search_service.parallel_search(request, provider_names=providers)
        result = response.model_dump()
        logger.debug(
            "tool result function=%s result=%s",
            "parallel_search",
            result,
            extra={"function": "parallel_search", "result": result},
        )
        return result

    @mcp.tool()
    async def fetch(urls: FetchUrls) -> dict:
        """Fetch known URLs as Markdown. Returns one result item per URL."""
        params = {"urls": urls}
        logger.info(
            "tool call function=%s params=%s",
            "fetch",
            params,
            extra={"function": "fetch", "params": params},
        )
        request = FetchRequest(urls=urls)
        response = await fetch_service.fetch(request.normalized_urls())
        result = response.model_dump()
        logger.debug(
            "tool result function=%s result=%s",
            "fetch",
            result,
            extra={"function": "fetch", "result": result},
        )
        return result

    for uri in RESOURCE_URIS:
        _register_resource(mcp, uri)

    return mcp


def _register_resource(mcp: FastMCP, uri: str) -> None:
    # Each call creates a new closure scope, so uri is captured correctly.
    @mcp.resource(uri)
    def read_resource() -> str:
        return resource_text_by_uri(uri)
