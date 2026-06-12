import logging

import httpx

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


async def test_build_search_providers_skips_unconfigured_paid_providers():
    assert await provider_names(Settings(TAVILY_API_KEY=None, EXA_API_KEY=None)) == ["duckduckgo"]


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
