import gzip
import threading

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


class ThreadRecordingMarkdownConverter:
    def __init__(self):
        self.thread_id = None

    def html_to_markdown(self, html, url=None):
        self.thread_id = threading.get_ident()
        return "# Hello\n\nThis page has enough readable content."


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
async def test_http_fetch_rejects_private_ip_by_default():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    provider = HttpFetchProvider(client=client, converter=FakeMarkdownConverter())

    with pytest.raises(ProviderError) as raised:
        await provider.fetch("http://127.0.0.1/admin")

    assert raised.value.error_type == ErrorType.INVALID_REQUEST
    await client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_allows_private_ip_when_explicitly_enabled():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<html><body><h1>Hello</h1></body></html>",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    converter = RecordingMarkdownConverter()
    provider = HttpFetchProvider(
        client=client,
        converter=converter,
        allow_private_fetch=True,
    )

    result = await provider.fetch("http://127.0.0.1/")

    assert result.status == "ok"
    assert converter.calls[0][1] == "http://127.0.0.1/"
    await client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_rejects_private_redirect_target():
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/":
            return httpx.Response(
                302,
                headers={"Location": "http://127.0.0.1/admin"},
                request=request,
            )
        return httpx.Response(200, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    provider = HttpFetchProvider(client=client, converter=FakeMarkdownConverter())

    with pytest.raises(ProviderError) as raised:
        await provider.fetch("https://example.com/")

    assert raised.value.error_type == ErrorType.INVALID_REQUEST
    await client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_rejects_body_larger_than_max_bytes():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"x" * 11,
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    provider = HttpFetchProvider(
        client=client,
        converter=FakeMarkdownConverter(),
        max_bytes=10,
    )

    with pytest.raises(ProviderError) as raised:
        await provider.fetch("https://example.com/")

    assert raised.value.error_type == ErrorType.UNSUPPORTED_CONTENT
    await client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_converts_markdown_off_event_loop_thread():
    loop_thread_id = threading.get_ident()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            content=b"<html><body><h1>Hello</h1></body></html>",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    converter = ThreadRecordingMarkdownConverter()
    provider = HttpFetchProvider(client=client, converter=converter)

    result = await provider.fetch("https://example.com/")

    assert result.status == "ok"
    assert converter.thread_id is not None
    assert converter.thread_id != loop_thread_id
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


@pytest.mark.asyncio
async def test_http_fetch_decompresses_gzip_response_without_double_decoding():
    # Servers return gzip-compressed bodies with Content-Encoding: gzip. The
    # provider reads decoded bytes via aiter_bytes() and must not hand the
    # rebuilt Response headers that would make httpx decode a second time
    # (previously raised DecodingError, masked by the size limit rejecting the
    # larger decompressed body first).
    raw_html = b"<html><body><h1>Hello</h1></body></html>"
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
            content=gzip.compress(raw_html),
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    provider = HttpFetchProvider(client=client, converter=FakeMarkdownConverter())

    result = await provider.fetch("https://example.com/")

    assert result.status == "ok"
    assert result.content == "# Hello\n\nThis page has enough readable content."
    await client.aclose()
