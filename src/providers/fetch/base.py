from __future__ import annotations

from typing import Protocol

from src.schemas import FetchProviderName, FetchResult


class FetchProvider(Protocol):
    name: FetchProviderName

    async def fetch(self, url: str) -> FetchResult:
        raise NotImplementedError
