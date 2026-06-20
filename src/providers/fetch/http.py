from __future__ import annotations

import asyncio
from ipaddress import ip_address

import httpx

from src.errors import ErrorType, ProviderError
from src.schemas import FetchProviderName, FetchResult
from src.utils.content_detection import looks_blocked
from src.utils.headers import get_fetch_headers
from src.utils.markdown import MarkdownConverter

MIN_MARKDOWN_LENGTH = 20
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


class HttpFetchProvider:
    name: FetchProviderName = "http"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        converter: MarkdownConverter | None = None,
        timeout: float = 20.0,
        max_bytes: int = 3_000_000,
        allow_private_fetch: bool = False,
        max_redirects: int = 10,
    ) -> None:
        self.client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self.converter = converter or MarkdownConverter()
        self.max_bytes = max_bytes
        self.allow_private_fetch = allow_private_fetch
        self.max_redirects = max_redirects

    async def fetch(self, url: str) -> FetchResult:
        try:
            response = await self._get_response(url)
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
        if 400 <= response.status_code < 500:
            raise ProviderError(
                error_type=ErrorType.INVALID_RESPONSE,
                provider=self.name,
                message=f"HTTP fetch returned {response.status_code}.",
                http_status=response.status_code,
            )
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
            markdown = await asyncio.to_thread(
                self.converter.html_to_markdown,
                html,
                final_url,
            )
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

    async def _get_response(self, url: str) -> httpx.Response:
        current_url = httpx.URL(url)
        for redirect_count in range(self.max_redirects + 1):
            self._validate_fetch_target(current_url)
            async with self.client.stream(
                "GET",
                current_url,
                headers=get_fetch_headers(),
                follow_redirects=False,
            ) as response:
                if response.status_code in REDIRECT_STATUS_CODES:
                    if redirect_count >= self.max_redirects:
                        raise ProviderError(
                            error_type=ErrorType.INVALID_RESPONSE,
                            provider=self.name,
                            message="HTTP fetch exceeded maximum redirects.",
                            http_status=response.status_code,
                        )
                    location = response.headers.get("Location")
                    if not location:
                        raise ProviderError(
                            error_type=ErrorType.INVALID_RESPONSE,
                            provider=self.name,
                            message="HTTP fetch redirect missing Location header.",
                            http_status=response.status_code,
                        )
                    current_url = response.url.join(location)
                    continue

                content = await self._read_limited_body(response)
                return httpx.Response(
                    status_code=response.status_code,
                    headers=response.headers,
                    content=content,
                    request=response.request,
                    extensions=response.extensions,
                )

        raise ProviderError(
            error_type=ErrorType.INVALID_RESPONSE,
            provider=self.name,
            message="HTTP fetch exceeded maximum redirects.",
        )

    async def _read_limited_body(self, response: httpx.Response) -> bytes:
        chunks = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                raise ProviderError(
                    error_type=ErrorType.UNSUPPORTED_CONTENT,
                    provider=self.name,
                    message="HTTP fetch exceeded maximum response size.",
                    http_status=response.status_code,
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _validate_fetch_target(self, url: httpx.URL) -> None:
        if self.allow_private_fetch:
            return
        host = url.host
        if not host:
            raise self._invalid_target("missing host")
        try:
            ip = ip_address(host)
        except ValueError:
            return
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
        ):
            raise self._invalid_target("private or local address")

    def _invalid_target(self, reason: str) -> ProviderError:
        return ProviderError(
            error_type=ErrorType.INVALID_REQUEST,
            provider=self.name,
            message=f"HTTP fetch target is not allowed: {reason}.",
        )
