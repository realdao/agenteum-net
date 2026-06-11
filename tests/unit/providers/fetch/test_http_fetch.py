import httpx
import pytest

from src.errors import ErrorType, ProviderError
from src.providers.fetch.http import HttpFetchProvider


class FakeMarkdownConverter:
    def html_to_markdown(self, html, url=None):
        assert "<h1>Hello</h1>" in html
        assert url == "https://example.com/"
        return "# Hello\n\nThis page has enough readable content."


class RecordingMarkdownConverter:
    def __init__(self):
        self.calls = []

    def html_to_markdown(self, html, url=None):
        self.calls.append((html, url))
        return "# Missing\n\nThis page has enough readable content."


@pytest.mark.asyncio
async def test_http_fetch_success_uses_headers_and_final_url():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "Mozilla/5.0" in request.headers["User-Agent"]
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<html><body><h1>Hello</h1></body></html>",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    provider = HttpFetchProvider(client=client, converter=FakeMarkdownConverter())

    result = await provider.fetch("https://example.com/")

    assert result.status == "ok"
    assert result.content == "# Hello\n\nThis page has enough readable content."
    assert result.final_url == "https://example.com/"
    await client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_non_html_raises_unsupported_content():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=b"%PDF")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HttpFetchProvider(client=client, converter=FakeMarkdownConverter())

    with pytest.raises(ProviderError) as raised:
        await provider.fetch("https://example.com/a.pdf")

    assert raised.value.error_type == ErrorType.UNSUPPORTED_CONTENT
    await client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_blocked_page_raises_blocked():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<title>Captcha</title><p>Verify you are human</p>",
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HttpFetchProvider(client=client, converter=FakeMarkdownConverter())

    with pytest.raises(ProviderError) as raised:
        await provider.fetch("https://example.com/")

    assert raised.value.error_type == ErrorType.BLOCKED
    await client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_404_html_raises_invalid_response_with_status():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            headers={"Content-Type": "text/html"},
            content=b"<html><body><h1>Not Found</h1></body></html>",
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    converter = RecordingMarkdownConverter()
    provider = HttpFetchProvider(client=client, converter=converter)

    with pytest.raises(ProviderError) as raised:
        await provider.fetch("https://example.com/missing")

    assert raised.value.error_type == ErrorType.INVALID_RESPONSE
    assert raised.value.http_status == 404
    assert converter.calls == []
    await client.aclose()
