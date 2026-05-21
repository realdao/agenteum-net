from __future__ import annotations

from typing import Any

import httpx

from src.errors import ErrorType, ProviderError
from src.schemas import SearchRequest, SearchResult

EXA_SEARCH_URL = "https://api.exa.ai/search"

_QUOTA_TAGS = {"NO_MORE_CREDITS", "API_KEY_BUDGET_EXCEEDED", "TEAM_BUDGET_EXCEEDED"}


class ExaSearchProvider:
    name = "exa"

    def __init__(
        self,
        *,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        if not self.api_key:
            raise ProviderError(
                error_type=ErrorType.CONFIG_ERROR,
                provider=self.name,
                message="EXA_API_KEY is not configured.",
            )

        payload: dict[str, Any] = {"query": request.query, "numResults": min(request.max_result, 20)}
        try:
            response = await self.client.post(
                EXA_SEARCH_URL,
                headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                error_type=ErrorType.TIMEOUT,
                provider=self.name,
                message="Exa request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                error_type=ErrorType.NETWORK,
                provider=self.name,
                message="Exa network error.",
            ) from exc

        if response.status_code != 200:
            raise self._error_from_response(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                error_type=ErrorType.INVALID_RESPONSE,
                provider=self.name,
                message="Exa returned malformed JSON.",
                http_status=response.status_code,
                payload=response.text,
            ) from exc

        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise ProviderError(
                error_type=ErrorType.INVALID_RESPONSE,
                provider=self.name,
                message="Exa response is missing results list.",
                http_status=response.status_code,
                payload=data,
            )

        return [
            SearchResult(
                title=str(item.get("title") or item.get("url") or ""),
                url=str(item.get("url") or ""),
                snippet=item.get("text") or item.get("summary") or _first_highlight(item),
                published_at=item.get("publishedDate") or item.get("published_at"),
                source="exa",
                score=item.get("score"),
            )
            for item in raw_results
            if item.get("url")
        ]

    def _error_from_response(self, response: httpx.Response) -> ProviderError:
        payload = _safe_response_payload(response)
        tag = payload.get("tag") if isinstance(payload, dict) else None
        if response.status_code == 400 or tag == "INVALID_REQUEST_BODY":
            error_type = ErrorType.INVALID_REQUEST
        elif response.status_code == 401 or tag == "INVALID_API_KEY":
            error_type = ErrorType.AUTH_ERROR
        elif response.status_code == 402 and tag in _QUOTA_TAGS:
            error_type = ErrorType.QUOTA_EXHAUSTED
        elif response.status_code == 403:
            error_type = ErrorType.AUTH_ERROR
        elif response.status_code == 429:
            error_type = ErrorType.RATE_LIMITED
        elif response.status_code in {500, 502, 503}:
            error_type = ErrorType.PROVIDER_5XX
        else:
            error_type = ErrorType.PROVIDER_ERROR
        return ProviderError(
            error_type=error_type,
            provider=self.name,
            message=f"Exa returned HTTP {response.status_code}.",
            http_status=response.status_code,
            payload=payload,
        )


def _first_highlight(item: dict[str, Any]) -> str | None:
    highlights = item.get("highlights")
    if isinstance(highlights, list) and highlights:
        return str(highlights[0])
    return None


def _safe_response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
