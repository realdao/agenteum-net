from __future__ import annotations

from typing import Protocol

from src.schemas import FetchResult


class FetchProvider(Protocol):
    name: str

    async def fetch(self, url: str) -> FetchResult:
        raise NotImplementedError
