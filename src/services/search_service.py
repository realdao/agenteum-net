from __future__ import annotations

import logging

from src.errors import ErrorType, ProviderError
from src.providers.search.base import SearchProvider
from src.schemas import FallbackRecord, SearchRequest, SearchResponse

FALLBACK_ERROR_TYPES = {
    ErrorType.QUOTA_EXHAUSTED,
    ErrorType.RATE_LIMITED,
    ErrorType.TIMEOUT,
    ErrorType.NETWORK,
    ErrorType.PROVIDER_5XX,
    ErrorType.INVALID_RESPONSE,
}


class SearchService:
    def __init__(
        self,
        providers: list[SearchProvider],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.providers = providers
        self.logger = logger or logging.getLogger(__name__)

    async def search(self, request: SearchRequest) -> SearchResponse:
        fallbacks: list[FallbackRecord] = []
        last_error: ProviderError | None = None

        for index, provider in enumerate(self.providers):
            try:
                results = await provider.search(request)
                return SearchResponse(
                    query=request.query,
                    results=results,
                    source=provider.name,
                    fallbacks=fallbacks,
                )
            except ProviderError as exc:
                last_error = exc
                if exc.error_type not in FALLBACK_ERROR_TYPES or index == len(self.providers) - 1:
                    raise
                next_provider = self.providers[index + 1]
                fallbacks.append(
                    FallbackRecord(
                        from_provider=provider.name,
                        to_provider=next_provider.name,
                        reason=exc.error_type.value,
                    )
                )
                self.logger.info(
                    "search provider fallback",
                    extra={
                        "operation": "search",
                        "from_provider": provider.name,
                        "to_provider": next_provider.name,
                        "reason": exc.error_type.value,
                        "fallback_count": len(fallbacks),
                    },
                )

        if last_error is not None:
            raise last_error
        raise ProviderError(
            error_type=ErrorType.CONFIG_ERROR,
            provider="search_service",
            message="No search providers configured.",
        )
