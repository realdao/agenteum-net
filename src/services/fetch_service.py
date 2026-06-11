from __future__ import annotations

import asyncio
import logging

from src.errors import ErrorType, ProviderError
from src.providers.fetch.base import FetchProvider
from src.schemas import FetchError, FetchProviderName, FetchResponse, FetchResult
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
        results = await asyncio.gather(
            *(self._fetch_one(url) for url in urls),
            return_exceptions=True,
        )
        return FetchResponse(
            results=[
                result
                if isinstance(result, FetchResult)
                else self._unexpected_error_result(url, result)
                for url, result in zip(urls, results, strict=True)
            ]
        )

    async def _fetch_one(self, url: str) -> FetchResult:
        if is_jina_first_url(url):
            return await self._fetch_with_item_error(self.jina_provider, url)

        try:
            return await self.http_provider.fetch(url)
        except ProviderError as exc:
            if self._should_fallback_to_jina(exc):
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
        except Exception as exc:
            return self._error_result(
                url,
                provider.name,
                ProviderError(
                    error_type=ErrorType.PROVIDER_ERROR,
                    provider=provider.name,
                    message=str(exc),
                ),
            )

    def _should_fallback_to_jina(self, exc: ProviderError) -> bool:
        if (
            exc.provider == "http"
            and exc.error_type == ErrorType.INVALID_RESPONSE
            and exc.http_status is not None
            and 400 <= exc.http_status < 500
        ):
            return False
        return exc.error_type in HTTP_TO_JINA_FALLBACK_ERRORS

    def _error_result(
        self,
        url: str,
        provider_name: FetchProviderName,
        exc: ProviderError,
    ) -> FetchResult:
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
                http_status=exc.http_status,
            ),
        )

    def _unexpected_error_result(self, url: str, exc: BaseException) -> FetchResult:
        if isinstance(exc, ProviderError):
            provider_name = self._fetch_provider_name(exc.provider)
            return self._error_result(url, provider_name, exc)
        return self._error_result(
            url,
            "http",
            ProviderError(
                error_type=ErrorType.PROVIDER_ERROR,
                provider="http",
                message=str(exc),
            ),
        )

    def _fetch_provider_name(self, provider: str) -> FetchProviderName:
        if provider == "jina":
            return "jina"
        return "http"
