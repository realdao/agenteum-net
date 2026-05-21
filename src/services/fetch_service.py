from __future__ import annotations

import asyncio
import logging

from src.errors import ErrorType, ProviderError
from src.providers.fetch.base import FetchProvider
from src.schemas import FetchError, FetchResponse, FetchResult
from src.utils.urls import is_jina_first_url

HTTP_TO_JINA_FALLBACK_ERRORS = {
    ErrorType.BLOCKED,
    ErrorType.EMPTY_CONTENT,
    ErrorType.TIMEOUT,
    ErrorType.NETWORK,
    ErrorType.PROVIDER_5XX,
    ErrorType.INVALID_RESPONSE,
}


class FetchService:
    def __init__(
        self,
        *,
        http_provider: FetchProvider,
        jina_provider: FetchProvider,
        logger: logging.Logger | None = None,
    ) -> None:
        self.http_provider = http_provider
        self.jina_provider = jina_provider
        self.logger = logger or logging.getLogger(__name__)

    async def fetch(self, urls: list[str]) -> FetchResponse:
        results = await asyncio.gather(*(self._fetch_one(url) for url in urls))
        return FetchResponse(results=list(results))

    async def _fetch_one(self, url: str) -> FetchResult:
        if is_jina_first_url(url):
            return await self._fetch_with_item_error(self.jina_provider, url)

        try:
            return await self.http_provider.fetch(url)
        except ProviderError as exc:
            if exc.error_type in HTTP_TO_JINA_FALLBACK_ERRORS:
                self.logger.info(
                    "fetch provider fallback",
                    extra={
                        "operation": "fetch",
                        "from_provider": "http",
                        "to_provider": "jina",
                        "reason": exc.error_type.value,
                        "fallback_count": 1,
                    },
                )
                return await self._fetch_with_item_error(self.jina_provider, url)
            return self._error_result(url, "http", exc)

    async def _fetch_with_item_error(self, provider: FetchProvider, url: str) -> FetchResult:
        try:
            return await provider.fetch(url)
        except ProviderError as exc:
            return self._error_result(url, provider.name, exc)

    def _error_result(self, url: str, provider_name: str, exc: ProviderError) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=None,
            content=None,
            source=provider_name,
            status="error",
            error=FetchError(
                type=exc.error_type.value,
                message=exc.message,
                provider=provider_name,
            ),
        )
