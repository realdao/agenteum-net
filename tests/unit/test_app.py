import contextlib
import logging

import httpx
import pytest

import src.app as app_module
from src.app import _build_search_providers, configure_logging
from src.config import Settings


async def provider_names(settings):
    client = httpx.AsyncClient()
    try:
        return [
            provider.name
            for provider in _build_search_providers(
                settings,
                client,
                logging.getLogger("test"),
            )
        ]
    finally:
        await client.aclose()


def test_configure_logging_uses_settings_log_level(monkeypatch):
    captured = {}

    def fake_basic_config(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    configure_logging(Settings(AGENTEUM_LOG_LEVEL="debug"))

    assert captured["level"] == logging.DEBUG
    assert "%(asctime)s" in captured["format"]


def test_create_app_passes_fetch_hardening_settings(monkeypatch):
    captured = {}

    class FakeHttpFetchProvider:
        name = "http"

        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def fetch(self, url):
            raise AssertionError("not called")

    monkeypatch.setattr(app_module, "HttpFetchProvider", FakeHttpFetchProvider)

    app_module.create_app(
        Settings(
            AGENTEUM_FETCH_MAX_BYTES=4096,
            AGENTEUM_ALLOW_PRIVATE_FETCH=True,
        )
    )

    assert captured["max_bytes"] == 4096
    assert captured["allow_private_fetch"] is True


async def test_create_app_closes_owned_http_clients_when_mcp_lifespan_exit_fails(monkeypatch):
    clients = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.closed = False
            clients.append(self)

        async def aclose(self):
            self.closed = True

    class FakeRouter:
        @contextlib.asynccontextmanager
        async def lifespan_context(self, app):
            try:
                yield
            finally:
                raise RuntimeError("mcp shutdown failed")

    class FakeMcpApp:
        router = FakeRouter()

        async def __call__(self, scope, receive, send):
            pass

    monkeypatch.setattr(app_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(app_module, "mount_mcp_streamable_http", lambda mcp: FakeMcpApp())

    app = app_module.create_app(Settings(TAVILY_API_KEY=None, EXA_API_KEY=None))

    with pytest.raises(RuntimeError, match="mcp shutdown failed"):
        async with app.router.lifespan_context(app):
            pass

    assert len(clients) == 3
    assert [client.closed for client in clients] == [True, True, True]


async def test_create_app_attempts_all_http_client_closes_when_first_close_fails(monkeypatch):
    clients = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.close_attempted = False
            self.close_error = RuntimeError("search close failed") if not clients else None
            clients.append(self)

        async def aclose(self):
            self.close_attempted = True
            if self.close_error:
                raise self.close_error

    class FakeRouter:
        @contextlib.asynccontextmanager
        async def lifespan_context(self, app):
            yield

    class FakeMcpApp:
        router = FakeRouter()

        async def __call__(self, scope, receive, send):
            pass

    monkeypatch.setattr(app_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(app_module, "mount_mcp_streamable_http", lambda mcp: FakeMcpApp())

    app = app_module.create_app(Settings(TAVILY_API_KEY=None, EXA_API_KEY=None))

    with pytest.raises(RuntimeError, match="search close failed"):
        async with app.router.lifespan_context(app):
            pass

    assert len(clients) == 3
    assert [client.close_attempted for client in clients] == [True, True, True]


async def test_build_search_providers_skips_unconfigured_paid_providers():
    assert await provider_names(Settings(TAVILY_API_KEY=None, EXA_API_KEY=None)) == ["duckduckgo"]


async def test_build_search_providers_passes_duckduckgo_timeout():
    client = httpx.AsyncClient()
    try:
        providers = _build_search_providers(
            Settings(
                TAVILY_API_KEY=None,
                EXA_API_KEY=None,
                AGENTEUM_DUCKDUCKGO_TIMEOUT=2.5,
            ),
            client,
            logging.getLogger("test"),
        )
        duckduckgo = providers[-1]
        assert duckduckgo.name == "duckduckgo"
        assert duckduckgo.timeout == 2.5
    finally:
        await client.aclose()


async def test_build_search_providers_includes_tavily_before_duckduckgo_when_configured():
    assert await provider_names(Settings(TAVILY_API_KEY="tavily-key", EXA_API_KEY=None)) == [
        "tavily",
        "duckduckgo",
    ]


async def test_build_search_providers_includes_exa_before_duckduckgo_when_configured():
    assert await provider_names(Settings(TAVILY_API_KEY=None, EXA_API_KEY="exa-key")) == [
        "exa",
        "duckduckgo",
    ]


async def test_build_search_providers_preserves_paid_provider_order_when_both_configured():
    assert await provider_names(Settings(TAVILY_API_KEY="tavily-key", EXA_API_KEY="exa-key")) == [
        "tavily",
        "exa",
        "duckduckgo",
    ]
