from __future__ import annotations

import asyncio

from ddgs import DDGS

from src.errors import ErrorType, ProviderError
from src.schemas import SearchRequest, SearchResult

_TIME_RANGE_MAP = {
    "day": "d",
    "d": "d",
    "week": "w",
    "w": "w",
    "month": "m",
    "m": "m",
    "year": "y",
    "y": "y",
}


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    def __init__(self, *, ddgs_factory: type[DDGS] = DDGS) -> None:
        self.ddgs_factory = ddgs_factory

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        try:
            return await asyncio.to_thread(self._search_sync, request)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                error_type=ErrorType.PROVIDER_ERROR,
                provider=self.name,
                message="DuckDuckGo search failed.",
                payload={"error": str(exc)},
            ) from exc

    def _search_sync(self, request: SearchRequest) -> list[SearchResult]:
        ddgs = self.ddgs_factory()
        timelimit = _TIME_RANGE_MAP.get(request.time_range or "")
        raw_results = ddgs.text(
            request.query,
            max_results=min(request.max_result, 20),
            timelimit=timelimit,
        )
        return [
            SearchResult(
                title=str(item.get("title") or item.get("href") or ""),
                url=str(item.get("href") or item.get("url") or ""),
                snippet=item.get("body") or item.get("snippet"),
                published_at=None,
                source="duckduckgo",
                score=None,
            )
            for item in raw_results
            if item.get("href") or item.get("url")
        ][: request.max_result]
