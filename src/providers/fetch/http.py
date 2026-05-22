from __future__ import annotations

import httpx

from src.errors import ErrorType, ProviderError
from src.schemas import FetchProviderName, FetchResult
from src.utils.content_detection import looks_blocked
from src.utils.headers import get_fetch_headers
from src.utils.markdown import MarkdownConverter

MIN_MARKDOWN_LENGTH = 20


class HttpFetchProvider:
    name: FetchProviderName = "http"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        converter: MarkdownConverter | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self.converter = converter or MarkdownConverter()

    async def fetch(self, url: str) -> FetchResult:
        try:
            response = await self.client.get(url, headers=get_fetch_headers())
        except httpx.TimeoutException as exc:
            raise ProviderError(
                error_type=ErrorType.TIMEOUT,
                provider=self.name,
                message="HTTP fetch timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                error_type=ErrorType.NETWORK,
                provider=self.name,
                message="HTTP fetch network error.",
            ) from exc

        final_url = str(response.url)
        content_type = response.headers.get("Content-Type", "").lower()
        if response.status_code >= 500:
            raise ProviderError(
                error_type=ErrorType.PROVIDER_5XX,
                provider=self.name,
                message=f"HTTP fetch returned {response.status_code}.",
                http_status=response.status_code,
            )
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise ProviderError(
                error_type=ErrorType.UNSUPPORTED_CONTENT,
                provider=self.name,
                message=f"Unsupported content type: {content_type or 'unknown'}.",
                http_status=response.status_code,
            )

        html = response.text
        if not html.strip():
            raise ProviderError(
                error_type=ErrorType.EMPTY_CONTENT,
                provider=self.name,
                message="HTTP fetch returned an empty body.",
                http_status=response.status_code,
            )
        if looks_blocked(html):
            raise ProviderError(
                error_type=ErrorType.BLOCKED,
                provider=self.name,
                message="HTTP fetch appears to be blocked.",
                http_status=response.status_code,
            )

        try:
            markdown = self.converter.html_to_markdown(html, final_url)
        except Exception as exc:
            raise ProviderError(
                error_type=ErrorType.INVALID_RESPONSE,
                provider=self.name,
                message="HTML to Markdown conversion failed.",
                http_status=response.status_code,
            ) from exc

        if len(markdown.strip()) < MIN_MARKDOWN_LENGTH:
            raise ProviderError(
                error_type=ErrorType.EMPTY_CONTENT,
                provider=self.name,
                message="Converted Markdown content is empty or too short.",
                http_status=response.status_code,
            )
        if looks_blocked(html, markdown):
            raise ProviderError(
                error_type=ErrorType.BLOCKED,
                provider=self.name,
                message="Converted Markdown appears to be blocked content.",
                http_status=response.status_code,
            )

        return FetchResult(
            url=url,
            final_url=final_url,
            content=markdown,
            source="http",
            status="ok",
            error=None,
        )
