from __future__ import annotations

import logging
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

from src.api.mcp_full import create_mcp_server
from src.api.transport import mount_mcp_streamable_http
from src.config import Settings, get_settings
from src.logging_config import setup_logging
from src.providers.fetch.http import HttpFetchProvider
from src.providers.fetch.jina import JinaFetchProvider
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

    app = FastAPI(title="Agenteum Net")

    search_client = httpx.AsyncClient(timeout=settings.request_timeout)
    fetch_client = httpx.AsyncClient(timeout=settings.fetch_timeout, follow_redirects=True)
    jina_client = httpx.AsyncClient(timeout=settings.jina_timeout)

    search_service = SearchService(
        [
            TavilySearchProvider(api_key=settings.tavily_api_key, client=search_client),
            ExaSearchProvider(api_key=settings.exa_api_key, client=search_client),
            DuckDuckGoSearchProvider(),
        ],
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
    mount_mcp_streamable_http(app, mcp=mcp, path="/mcp/full")
    return app


def main() -> None:
    settings = get_settings()
    log_dir = Path(__file__).parent.parent / "logs"
    setup_logging(level=logging.INFO, log_dir=log_dir if log_dir.exists() else None)
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port)
