from __future__ import annotations

from typing import Protocol

from src.schemas import SearchRequest, SearchResult


class SearchProvider(Protocol):
    name: str

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        raise NotImplementedError
