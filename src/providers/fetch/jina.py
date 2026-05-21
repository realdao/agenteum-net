from __future__ import annotations

import httpx

from src.errors import ErrorType, ProviderError
from src.schemas import FetchResult

JINA_READER_BASE_URL = "https://r.jina.ai"


class JinaFetchProvider:
    name = "jina"

    def __init__(
        self,
        *,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def fetch(self, url: str) -> FetchResult:
        if not self.api_key:
            raise ProviderError(
                error_type=ErrorType.CONFIG_ERROR,
                provider=self.name,
                message="JINA_API_KEY is not configured.",
            )

        reader_url = f"{JINA_READER_BASE_URL}/{url}"
        try:
            response = await self.client.get(
                reader_url,
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "text/markdown"},
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                error_type=ErrorType.TIMEOUT,
                provider=self.name,
                message="Jina request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                error_type=ErrorType.NETWORK,
                provider=self.name,
                message="Jina network error.",
            ) from exc

        if response.status_code >= 500:
            raise ProviderError(
                error_type=ErrorType.PROVIDER_5XX,
                provider=self.name,
                message=f"Jina returned HTTP {response.status_code}.",
                http_status=response.status_code,
                payload=response.text,
            )
        if response.status_code in {401, 403}:
            raise ProviderError(
                error_type=ErrorType.AUTH_ERROR,
                provider=self.name,
                message=f"Jina returned HTTP {response.status_code}.",
                http_status=response.status_code,
            )
        if response.status_code != 200:
            raise ProviderError(
                error_type=ErrorType.PROVIDER_ERROR,
                provider=self.name,
                message=f"Jina returned HTTP {response.status_code}.",
                http_status=response.status_code,
                payload=response.text,
            )

        markdown = response.text.strip()
        if not markdown:
            raise ProviderError(
                error_type=ErrorType.EMPTY_CONTENT,
                provider=self.name,
                message="Jina returned empty content.",
                http_status=response.status_code,
            )

        final_url = response.headers.get("X-Final-Url") or url
        return FetchResult(
            url=url,
            final_url=final_url,
            content=markdown,
            source="jina",
            status="ok",
            error=None,
        )
