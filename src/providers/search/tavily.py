from __future__ import annotations

from typing import Any

import httpx

from src.errors import ErrorType, ProviderError
from src.schemas import SearchRequest, SearchResult

TAVILY_SEARCH_URL = "https://api.tavily.com/search"

_TIME_RANGE_MAP = {
    "day": "day",
    "d": "day",
    "week": "week",
    "w": "week",
    "month": "month",
    "m": "month",
    "year": "year",
    "y": "year",
}

_TOPIC_MAP = {"general": "general", "news": "news", "finance": "finance"}


class TavilySearchProvider:
    name = "tavily"

    def __init__(
        self,
        *,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self.timeout = timeout

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        if not self.api_key:
            raise ProviderError(
                error_type=ErrorType.CONFIG_ERROR,
                provider=self.name,
                message="TAVILY_API_KEY is not configured.",
            )

        payload: dict[str, Any] = {
            "query": request.query,
            "max_results": min(request.max_result, 20),
            "search_depth": "basic",
            "include_answer": False,
        }
        if request.time_range and request.time_range in _TIME_RANGE_MAP:
            payload["time_range"] = _TIME_RANGE_MAP[request.time_range]
        if request.topic and request.topic in _TOPIC_MAP:
            payload["topic"] = _TOPIC_MAP[request.topic]

        try:
            response = await self.client.post(
                TAVILY_SEARCH_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                error_type=ErrorType.TIMEOUT,
                provider=self.name,
                message="Tavily request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                error_type=ErrorType.NETWORK,
                provider=self.name,
                message="Tavily network error.",
            ) from exc

        if response.status_code != 200:
            raise self._error_from_response(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                error_type=ErrorType.INVALID_RESPONSE,
                provider=self.name,
                message="Tavily returned malformed JSON.",
                http_status=response.status_code,
                payload=response.text,
            ) from exc

        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise ProviderError(
                error_type=ErrorType.INVALID_RESPONSE,
                provider=self.name,
                message="Tavily response is missing results list.",
                http_status=response.status_code,
                payload=data,
            )

        return [
            SearchResult(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                snippet=item.get("content"),
                published_at=item.get("published_date") or item.get("published_at"),
                source="tavily",
                score=item.get("score"),
            )
            for item in raw_results
            if item.get("url")
        ]

    def _error_from_response(self, response: httpx.Response) -> ProviderError:
        error_type = {
            400: ErrorType.INVALID_REQUEST,
            401: ErrorType.AUTH_ERROR,
            403: ErrorType.AUTH_ERROR,
            429: ErrorType.RATE_LIMITED,
            432: ErrorType.QUOTA_EXHAUSTED,
            433: ErrorType.QUOTA_EXHAUSTED,
        }.get(response.status_code)
        if error_type is None and response.status_code >= 500:
            error_type = ErrorType.PROVIDER_5XX
        if error_type is None:
            error_type = ErrorType.PROVIDER_ERROR
        return ProviderError(
            error_type=error_type,
            provider=self.name,
            message=f"Tavily returned HTTP {response.status_code}.",
            http_status=response.status_code,
            payload=_safe_response_payload(response),
        )


def _safe_response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
