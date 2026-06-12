from __future__ import annotations

import asyncio
import logging
from urllib.parse import urldefrag

from src.errors import ErrorType, ProviderError
from src.providers.search.base import SearchProvider
from src.schemas import (
    FallbackRecord,
    ParallelSearchResponse,
    SearchProviderError,
    SearchProviderName,
    SearchRequest,
    SearchResponse,
    SearchResult,
)

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

    async def parallel_search(
        self,
        request: SearchRequest,
        provider_names: list[str] | None = None,
    ) -> ParallelSearchResponse:
        selected_providers = self._select_parallel_providers(provider_names)
        tasks = [provider.search(request) for provider in selected_providers]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[SearchResult] = []
        sources: list[SearchProviderName] = []
        errors: list[SearchProviderError] = []
        last_error: ProviderError | None = None

        for provider, provider_result in zip(selected_providers, raw_results, strict=True):
            if isinstance(provider_result, ProviderError):
                last_error = provider_result
                errors.append(
                    SearchProviderError(
                        provider=provider.name,
                        type=provider_result.error_type.value,
                        message=provider_result.message,
                        http_status=provider_result.http_status,
                        request_id=provider_result.request_id,
                    )
                )
                continue
            if isinstance(provider_result, Exception):
                last_error = ProviderError(
                    error_type=ErrorType.PROVIDER_ERROR,
                    provider=provider.name,
                    message=str(provider_result),
                )
                errors.append(
                    SearchProviderError(
                        provider=provider.name,
                        type=last_error.error_type.value,
                        message=last_error.message,
                    )
                )
                continue

            sources.append(provider.name)
            results.extend(provider_result)

        if not sources:
            if last_error is not None:
                raise last_error
            raise ProviderError(
                error_type=ErrorType.CONFIG_ERROR,
                provider="search_service",
                message="No search providers configured.",
            )

        return ParallelSearchResponse(
            query=request.query,
            results=_deduplicate_results_by_url(results),
            sources=sources,
            errors=errors,
        )

    def _select_parallel_providers(self, provider_names: list[str] | None) -> list[SearchProvider]:
        if not provider_names:
            return self.providers

        providers_by_name = {provider.name: provider for provider in self.providers}
        selected_providers: list[SearchProvider] = []
        seen_provider_names: set[str] = set()
        for provider_name in provider_names:
            if provider_name in seen_provider_names:
                continue
            provider = providers_by_name.get(provider_name)
            if provider is None:
                raise ProviderError(
                    error_type=ErrorType.INVALID_REQUEST,
                    provider="search_service",
                    message=f"Unknown search provider: {provider_name}.",
                )
            seen_provider_names.add(provider_name)
            selected_providers.append(provider)
        return selected_providers


def _deduplicate_results_by_url(results: list[SearchResult]) -> list[SearchResult]:
    seen_urls: set[str] = set()
    deduplicated: list[SearchResult] = []
    for result in results:
        normalized_url = _normalize_url_for_deduplication(result.url)
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        deduplicated.append(result)
    return deduplicated


def _normalize_url_for_deduplication(url: str) -> str:
    return urldefrag(url).url.rstrip("/")
