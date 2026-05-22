from __future__ import annotations

from urllib.parse import urlparse

JINA_FIRST_HOSTS = ("x.com", "twitter.com")


def hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_jina_first_url(url: str) -> bool:
    host = hostname(url)
    return any(host == expected or host.endswith(f".{expected}") for expected in JINA_FIRST_HOSTS)
