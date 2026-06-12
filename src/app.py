from __future__ import annotations

import contextlib
import logging

import httpx
import uvicorn
from fastapi import FastAPI

from src.api.mcp_full import create_mcp_server
from src.api.transport import mount_mcp_streamable_http
from src.config import Settings, get_settings
from src.providers.fetch.http import HttpFetchProvider
from src.providers.fetch.jina import JinaFetchProvider
from src.providers.search.base import SearchProvider
from src.providers.search.duckduckgo import DuckDuckGoSearchProvider
from src.providers.search.exa import ExaSearchProvider
from src.providers.search.tavily import TavilySearchProvider
from src.services.fetch_service import FetchService
from src.services.search_service import SearchService
from src.utils.markdown import MarkdownConverter


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logger = logging.getLogger("agenteum_net")
    settings.validate_network_binding(logger)

    search_client = httpx.AsyncClient(timeout=settings.request_timeout)
    fetch_client = httpx.AsyncClient(timeout=settings.fetch_timeout, follow_redirects=True)
    jina_client = httpx.AsyncClient(timeout=settings.jina_timeout)

    search_service = SearchService(
        _build_search_providers(settings, search_client, logger),
        logger=logger,
    )
    fetch_service = FetchService(
        http_provider=HttpFetchProvider(
            client=fetch_client,
            converter=MarkdownConverter(),
        ),
        jina_provider=JinaFetchProvider(api_key=settings.jina_api_key, client=jina_client),
        logger=logger,
    )

    mcp = create_mcp_server(search_service=search_service, fetch_service=fetch_service)
    mcp_app = mount_mcp_streamable_http(mcp)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            async with mcp_app.router.lifespan_context(mcp_app):
                yield
        finally:
            await search_client.aclose()
            await fetch_client.aclose()
            await jina_client.aclose()

    app = FastAPI(title="Agenteum Net", lifespan=lifespan)
    app.mount("/mcp/full", mcp_app)
    return app


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port)


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _build_search_providers(
    settings: Settings,
    search_client: httpx.AsyncClient,
    logger: logging.Logger,
) -> list[SearchProvider]:
    providers: list[SearchProvider] = []

    if settings.tavily_api_key:
        providers.append(
            TavilySearchProvider(api_key=settings.tavily_api_key, client=search_client)
        )
    else:
        logger.info("Tavily search provider disabled because TAVILY_API_KEY is not configured.")

    if settings.exa_api_key:
        providers.append(ExaSearchProvider(api_key=settings.exa_api_key, client=search_client))
    else:
        logger.info("Exa search provider disabled because EXA_API_KEY is not configured.")

    providers.append(DuckDuckGoSearchProvider())
    return providers
