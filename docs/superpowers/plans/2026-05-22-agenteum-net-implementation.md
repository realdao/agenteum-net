# Agenteum Net v1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v1.0 HTTP-only MCP server with `agenteum_search` and `agenteum_fetch`, backed by Tavily, Exa, DuckDuckGo, HTTP fetch, and Jina.

**Architecture:** Keep provider logic, service strategy, MCP registration, and transport mounting separate. Providers translate external APIs into unified schemas and internal errors; services own fallback/routing policy; the API layer only exposes tools/resources through MCP Streamable HTTP.

**Tech Stack:** Python 3.11+, uv, official MCP Python SDK Streamable HTTP, FastAPI, httpx, Pydantic v2, Pydantic Settings, MarkItDown, ddgs, pytest, pytest-asyncio, ruff.

---

## References

- Design spec: `docs/superpowers/specs/2026-05-22-agenteum-net-design.md`
- Commit rule: `AGENTS.md` and `rules/git-commit-standards.md`
- MCP endpoint: `/mcp/full`
- Commit command shown in this plan uses Codex identity. If a different agent executes a task, use that agent's name and email according to `rules/git-commit-standards.md`.

## File Map

- `pyproject.toml`: uv project metadata, dependencies, pytest config, ruff config, package discovery for the direct `src` package.
- `.env.example`: documented runtime settings without real secrets.
- `README.md`: local run instructions, WSL/remote binding warning, tool overview.
- `src/__init__.py`: package marker and version.
- `src/schemas.py`: Pydantic contracts for tool inputs, outputs, results, fallbacks, and errors.
- `src/errors.py`: internal error enum, provider exception, safe log representation.
- `src/config.py`: environment settings and remote binding validation.
- `src/utils/headers.py`: fixed fetch headers and fixed User-Agent helper.
- `src/utils/content_detection.py`: conservative blocked-page detection.
- `src/utils/markdown.py`: MarkItDown wrapper for already-fetched HTML.
- `src/utils/urls.py`: HTTP URL validation and Jina-first host detection.
- `src/utils/logging.py`: structured logging helpers and provider latency context.
- `src/providers/search/base.py`: search provider protocol.
- `src/providers/search/tavily.py`: Tavily REST provider.
- `src/providers/search/exa.py`: Exa REST provider.
- `src/providers/search/duckduckgo.py`: ddgs-backed DuckDuckGo wrapper.
- `src/providers/fetch/base.py`: fetch provider protocol.
- `src/providers/fetch/http.py`: HTTP HTML fetch provider.
- `src/providers/fetch/jina.py`: Jina Reader provider.
- `src/services/search_service.py`: Tavily -> Exa -> DuckDuckGo fallback.
- `src/services/fetch_service.py`: URL routing, HTTP-first fetch, Jina fallback, partial failure handling.
- `src/resources/search-guide.md`: MCP search guide resource body.
- `src/resources/fetch-guide.md`: MCP fetch guide resource body.
- `src/resources/providers-capabilities.md`: provider capability resource body.
- `src/resources/tool_guides.py`: resource file loader and MCP resource registration helper.
- `src/api/mcp_full.py`: MCP tools/resources registration, dependency wiring.
- `src/api/transport.py`: official SDK Streamable HTTP mounting.
- `src/app.py`: FastAPI app creation and CLI entry point.
- `tests/unit/`: provider, service, schema, config, utility, and API unit tests.
- `tests/smoke/`: MCP protocol smoke tests.

## Implementation Decisions

- Top-level search failure: raise `ProviderError` from the service. The MCP tool lets the SDK return a tool error rather than returning a partial `SearchResponse` with an invented error field.
- Request timeouts:
  - `AGENTEUM_REQUEST_TIMEOUT=15.0`
  - `AGENTEUM_FETCH_TIMEOUT=20.0`
  - `AGENTEUM_JINA_TIMEOUT=30.0`
- Fetch batch size: exactly 10 URLs, enforced by `FetchRequest`.
- Search `max_result`: 1 to 20, enforced by `SearchRequest`; providers may adapt lower limits internally.
- Fetch execution: use `asyncio.gather()` to fetch URL items concurrently while preserving output order.
- DuckDuckGo: use a wrapper around `ddgs.DDGS`; service and tests depend on the wrapper shape, not on ddgs internals.
- MarkItDown: the HTTP provider fetches HTML with httpx, then passes a binary stream into a `MarkdownConverter`.

---

### Task 1: Project Metadata And Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `README.md`
- Create: `src/__init__.py`
- Create package directories under `src/` and `tests/`

- [ ] **Step 1: Write the failing project smoke test**

Create `tests/smoke/test_project_imports.py`:

```python
def test_src_package_imports():
    import src

    assert src.__version__ == "0.1.0"
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run:

```bash
uv run pytest tests/smoke/test_project_imports.py -v
```

Expected: fail because `pyproject.toml` and `src` do not exist yet.

- [ ] **Step 3: Create project metadata**

Create `pyproject.toml`:

```toml
[project]
name = "agenteum-net"
version = "0.1.0"
description = "HTTP-only MCP server for agent web search and fetch providers."
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "ddgs>=9.14.2,<10",
  "fastapi>=0.115,<1",
  "httpx>=0.28,<1",
  "markitdown>=0.1.5,<0.2",
  "mcp>=1.27.1,<2",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.9,<3",
  "python-dotenv>=1,<2",
  "uvicorn[standard]>=0.34,<1",
]

[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"

[project.scripts]
agenteum-net = "src.app:main"

[dependency-groups]
dev = [
  "pytest>=8.3,<9",
  "pytest-asyncio>=0.26,<1",
  "ruff>=0.11,<1",
]

[tool.setuptools.packages.find]
include = ["src*"]

[tool.setuptools.package-data]
"src.resources" = ["*.md"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

Create `.env.example`:

```env
AGENTEUM_HOST=127.0.0.1
AGENTEUM_PORT=8765
AGENTEUM_ALLOW_REMOTE=false
AGENTEUM_REQUEST_TIMEOUT=15.0
AGENTEUM_FETCH_TIMEOUT=20.0
AGENTEUM_JINA_TIMEOUT=30.0
TAVILY_API_KEY=
EXA_API_KEY=
JINA_API_KEY=
```

Create `README.md`:

```markdown
# Agenteum Net

Agenteum Net is an HTTP-only MCP server that exposes web search and web fetch tools for local agent clients.

## v1.0 Tools

- `agenteum_search(query, max_result=10, time_range=None, topic=None)`
- `agenteum_fetch(urls)`

## Local Run

```bash
uv sync
uv run agenteum-net
```

The MCP endpoint is available at:

```text
http://127.0.0.1:8765/mcp/full
```

## WSL Access

The server binds to `127.0.0.1` by default. For WSL clients that need host-visible binding:

```env
AGENTEUM_HOST=0.0.0.0
AGENTEUM_ALLOW_REMOTE=true
```

v1.0 has no authentication. Do not expose a remote bind address to an untrusted network.
```

- [ ] **Step 4: Create package directories**

Run:

```bash
mkdir src src\api src\providers src\providers\search src\providers\fetch src\services src\resources src\utils tests\unit tests\unit\api tests\unit\providers tests\unit\providers\search tests\unit\providers\fetch tests\unit\services tests\unit\utils tests\smoke
```

Create `src/__init__.py`:

```python
__version__ = "0.1.0"
```

Create empty `__init__.py` files in:

```text
src/api/__init__.py
src/providers/__init__.py
src/providers/search/__init__.py
src/providers/fetch/__init__.py
src/services/__init__.py
src/resources/__init__.py
src/utils/__init__.py
```

- [ ] **Step 5: Install dependencies and run the smoke test**

Run:

```bash
uv sync
uv run pytest tests/smoke/test_project_imports.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add pyproject.toml .env.example README.md src tests
git -c user.name=Codex -c user.email=codex@agenteum.com commit --author="Codex <codex@agenteum.com>" -m "chore: scaffold python project"
```

---

### Task 2: Schemas And Internal Errors

**Files:**
- Create: `src/schemas.py`
- Create: `src/errors.py`
- Test: `tests/unit/test_schemas.py`
- Test: `tests/unit/test_errors.py`

- [ ] **Step 1: Write failing schema tests**

Create `tests/unit/test_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from src.schemas import (
    FetchRequest,
    FetchResponse,
    FetchResult,
    SearchRequest,
    SearchResponse,
    SearchResult,
)


def test_search_request_caps_max_result_at_twenty():
    request = SearchRequest(query="python mcp", max_result=20)

    assert request.max_result == 20


def test_search_request_rejects_too_many_results():
    with pytest.raises(ValidationError):
        SearchRequest(query="python mcp", max_result=21)


def test_search_response_serializes_unified_results():
    result = SearchResult(
        title="Example",
        url="https://example.com",
        snippet="Example snippet",
        published_at=None,
        source="tavily",
        score=0.9,
    )
    response = SearchResponse(query="example", results=[result], source="tavily", fallbacks=[])

    assert response.model_dump()["results"][0]["source"] == "tavily"


def test_fetch_request_rejects_more_than_ten_urls():
    with pytest.raises(ValidationError):
        FetchRequest(urls=[f"https://example.com/{index}" for index in range(11)])


def test_fetch_request_rejects_non_http_urls():
    with pytest.raises(ValidationError):
        FetchRequest(urls=["file:///tmp/example.html"])


def test_fetch_response_allows_item_level_error():
    item = FetchResult(
        url="https://blocked.example",
        final_url=None,
        content=None,
        source="http",
        status="error",
        error={"type": "blocked", "message": "Blocked page", "provider": "http"},
    )
    response = FetchResponse(results=[item])

    assert response.results[0].status == "error"
    assert response.results[0].error is not None
```

- [ ] **Step 2: Write failing error tests**

Create `tests/unit/test_errors.py`:

```python
from src.errors import ErrorType, ProviderError, redact_payload


def test_provider_error_safe_repr_redacts_secrets_and_truncates_payload():
    error = ProviderError(
        error_type=ErrorType.AUTH_ERROR,
        provider="tavily",
        message="bad key",
        http_status=401,
        payload={
            "api_key": "secret-key",
            "nested": {"authorization": "Bearer secret-token"},
            "body": "x" * 600,
        },
    )

    safe = error.safe_repr()

    assert safe["error_type"] == "auth_error"
    assert safe["provider"] == "tavily"
    assert safe["payload"]["api_key"] == "[REDACTED]"
    assert safe["payload"]["nested"]["authorization"] == "[REDACTED]"
    assert safe["payload"]["body"].endswith("[TRUNCATED]")
    assert len(safe["payload"]["body"]) < 530


def test_redact_payload_handles_lists():
    payload = [{"token": "secret"}, {"value": "visible"}]

    assert redact_payload(payload)[0]["token"] == "[REDACTED]"
    assert redact_payload(payload)[1]["value"] == "visible"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_schemas.py tests/unit/test_errors.py -v
```

Expected: fail because `src.schemas` and `src.errors` do not exist.

- [ ] **Step 4: Implement errors**

Create `src/errors.py`:

```python
from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorType(StrEnum):
    QUOTA_EXHAUSTED = "quota_exhausted"
    RATE_LIMITED = "rate_limited"
    AUTH_ERROR = "auth_error"
    CONFIG_ERROR = "config_error"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE = "invalid_response"
    TIMEOUT = "timeout"
    NETWORK = "network"
    PROVIDER_5XX = "provider_5xx"
    BLOCKED = "blocked"
    EMPTY_CONTENT = "empty_content"
    UNSUPPORTED_CONTENT = "unsupported_content"
    PROVIDER_ERROR = "provider_error"


SECRET_KEYS = ("api_key", "authorization", "token", "secret", "password")
MAX_PAYLOAD_TEXT = 500


def _is_secret_key(key: str) -> bool:
    key_lower = key.lower()
    return any(secret in key_lower for secret in SECRET_KEYS)


def _truncate(value: str) -> str:
    if len(value) <= MAX_PAYLOAD_TEXT:
        return value
    return f"{value[:MAX_PAYLOAD_TEXT]}[TRUNCATED]"


def redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: "[REDACTED]" if _is_secret_key(str(key)) else redact_payload(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(redact_payload(item) for item in payload)
    if isinstance(payload, str):
        return _truncate(payload)
    return payload


class ProviderError(Exception):
    def __init__(
        self,
        *,
        error_type: ErrorType,
        provider: str,
        message: str,
        http_status: int | None = None,
        request_id: str | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.provider = provider
        self.message = message
        self.http_status = http_status
        self.request_id = request_id
        self.payload = payload

    def safe_repr(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type.value,
            "provider": self.provider,
            "message": self.message,
            "http_status": self.http_status,
            "request_id": self.request_id,
            "payload": redact_payload(self.payload),
        }
```

- [ ] **Step 5: Implement schemas**

Create `src/schemas.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["tavily", "exa", "duckduckgo", "http", "jina"]
SearchProviderName = Literal["tavily", "exa", "duckduckgo"]
FetchProviderName = Literal["http", "jina"]
FetchStatus = Literal["ok", "error"]
TimeRange = Literal["day", "week", "month", "year", "d", "w", "m", "y"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    max_result: int = Field(default=10, ge=1, le=20)
    time_range: TimeRange | None = None
    topic: str | None = None

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str | None = None
    published_at: str | None = None
    source: SearchProviderName
    score: float | None = None


class FallbackRecord(BaseModel):
    from_provider: SearchProviderName = Field(alias="from")
    to_provider: SearchProviderName = Field(alias="to")
    reason: str

    model_config = ConfigDict(populate_by_name=True)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    source: SearchProviderName
    fallbacks: list[FallbackRecord] = Field(default_factory=list)


class FetchError(BaseModel):
    type: str
    message: str
    provider: FetchProviderName


class FetchResult(BaseModel):
    url: str
    final_url: str | None = None
    content: str | None = None
    source: FetchProviderName
    status: FetchStatus
    error: FetchError | dict[str, str] | None = None


class FetchRequest(BaseModel):
    urls: list[AnyHttpUrl] = Field(min_length=1, max_length=10)

    def normalized_urls(self) -> list[str]:
        return [str(url) for url in self.urls]


class FetchResponse(BaseModel):
    results: list[FetchResult]
```

- [ ] **Step 6: Run unit tests**

Run:

```bash
uv run pytest tests/unit/test_schemas.py tests/unit/test_errors.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/schemas.py src/errors.py tests/unit/test_schemas.py tests/unit/test_errors.py
git -c user.name=Codex -c user.email=codex@agenteum.com commit --author="Codex <codex@agenteum.com>" -m "feat: add schemas and provider errors"
```

---

### Task 3: Configuration And Utilities

**Files:**
- Create: `src/config.py`
- Create: `src/utils/headers.py`
- Create: `src/utils/content_detection.py`
- Create: `src/utils/urls.py`
- Create: `src/utils/markdown.py`
- Create: `src/utils/logging.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/utils/test_headers.py`
- Test: `tests/unit/utils/test_content_detection.py`
- Test: `tests/unit/utils/test_urls.py`
- Test: `tests/unit/utils/test_markdown.py`

- [ ] **Step 1: Write failing config and utility tests**

Create `tests/unit/test_config.py`:

```python
import logging

import pytest

from src.config import Settings


def test_default_settings_bind_to_loopback():
    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.allow_remote is False


def test_remote_binding_requires_explicit_flag():
    settings = Settings(AGENTEUM_HOST="0.0.0.0", AGENTEUM_ALLOW_REMOTE=False)

    with pytest.raises(ValueError, match="AGENTEUM_ALLOW_REMOTE=true"):
        settings.validate_network_binding(logging.getLogger("test"))


def test_remote_binding_logs_warning_when_allowed(caplog):
    settings = Settings(AGENTEUM_HOST="0.0.0.0", AGENTEUM_ALLOW_REMOTE=True)

    with caplog.at_level(logging.WARNING):
        settings.validate_network_binding(logging.getLogger("test"))

    assert "no authentication" in caplog.text
```

Create `tests/unit/utils/test_headers.py`:

```python
from src.utils.headers import get_fetch_headers


def test_fetch_headers_include_required_values():
    headers = get_fetch_headers()

    assert "Mozilla/5.0" in headers["User-Agent"]
    assert "text/html" in headers["Accept"]
    assert headers["Accept-Language"].startswith("zh-CN")
```

Create `tests/unit/utils/test_content_detection.py`:

```python
from src.utils.content_detection import extract_title, looks_blocked


def test_extract_title_reads_html_title():
    title = extract_title("<html><head><title>Access Denied</title></head></html>")

    assert title == "Access Denied"


def test_blocked_detector_flags_captcha_page():
    assert looks_blocked("<title>Captcha</title>", "Verify you are human")


def test_blocked_detector_avoids_ordinary_cloudflare_article():
    html = "<title>Cloudflare architecture notes</title>"
    markdown = "# Cloudflare architecture notes\n\nA long ordinary article body. " * 80

    assert not looks_blocked(html, markdown)
```

Create `tests/unit/utils/test_urls.py`:

```python
from src.utils.urls import is_http_url, is_jina_first_url


def test_http_url_validation():
    assert is_http_url("https://example.com")
    assert not is_http_url("file:///tmp/a.html")


def test_jina_first_domains():
    assert is_jina_first_url("https://x.com/openai/status/1")
    assert is_jina_first_url("https://twitter.com/openai/status/1")
    assert not is_jina_first_url("https://example.com")
```

Create `tests/unit/utils/test_markdown.py`:

```python
from src.utils.markdown import MarkdownConverter


class FakeMarkItDown:
    def convert_stream(self, stream, file_extension=None, url=None):
        body = stream.read().decode("utf-8")
        assert "<h1>Hello</h1>" in body
        assert file_extension == ".html"
        assert url == "https://example.com"

        class Result:
            text_content = "# Hello"

        return Result()


def test_markdown_converter_uses_binary_stream():
    converter = MarkdownConverter(markitdown=FakeMarkItDown())

    assert converter.html_to_markdown("<h1>Hello</h1>", "https://example.com") == "# Hello"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_config.py tests/unit/utils -v
```

Expected: fail because utility modules do not exist.

- [ ] **Step 3: Implement config**

Create `src/config.py`:

```python
from __future__ import annotations

import logging
from functools import lru_cache
from ipaddress import ip_address

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    host: str = Field(default="127.0.0.1", alias="AGENTEUM_HOST")
    port: int = Field(default=8765, alias="AGENTEUM_PORT")
    allow_remote: bool = Field(default=False, alias="AGENTEUM_ALLOW_REMOTE")
    request_timeout: float = Field(default=15.0, alias="AGENTEUM_REQUEST_TIMEOUT")
    fetch_timeout: float = Field(default=20.0, alias="AGENTEUM_FETCH_TIMEOUT")
    jina_timeout: float = Field(default=30.0, alias="AGENTEUM_JINA_TIMEOUT")
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    exa_api_key: str | None = Field(default=None, alias="EXA_API_KEY")
    jina_api_key: str | None = Field(default=None, alias="JINA_API_KEY")

    def validate_network_binding(self, logger: logging.Logger) -> None:
        if not is_remote_bind_host(self.host):
            return
        if not self.allow_remote:
            raise ValueError(
                "Remote bind hosts require AGENTEUM_ALLOW_REMOTE=true because v1.0 has no authentication."
            )
        logger.warning(
            "Agenteum Net is listening on a remote bind host with no authentication.",
            extra={"host": self.host, "port": self.port, "security": "no_authentication"},
        )


def is_remote_bind_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return False
    if normalized in {"0.0.0.0", "::", ""}:
        return True
    try:
        return not ip_address(normalized).is_loopback
    except ValueError:
        return True


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Implement utility modules**

Create `src/utils/headers.py`:

```python
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

FETCH_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def get_default_user_agent() -> str:
    return DEFAULT_USER_AGENT


def get_fetch_headers() -> dict[str, str]:
    return dict(FETCH_HEADERS)
```

Create `src/utils/content_detection.py`:

```python
from __future__ import annotations

import re

STRONG_BLOCKED_MARKERS = (
    "access denied",
    "captcha",
    "checking your browser",
    "enable javascript",
    "verify you are human",
    "unusual traffic",
    "bot detection",
    "temporarily blocked",
)

WEAK_BLOCKED_MARKERS = ("cloudflare", "forbidden")

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def extract_title(html: str) -> str:
    match = TITLE_RE.search(html)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def looks_blocked(html: str, markdown: str | None = None) -> bool:
    markdown_text = markdown or ""
    title = extract_title(html).lower()
    combined = f"{title}\n{html}\n{markdown_text}".lower()
    if any(marker in combined for marker in STRONG_BLOCKED_MARKERS):
        return True
    if any(marker in title for marker in WEAK_BLOCKED_MARKERS) and len(markdown_text) < 500:
        return True
    return False
```

Create `src/utils/urls.py`:

```python
from __future__ import annotations

from urllib.parse import urlparse

JINA_FIRST_HOSTS = ("x.com", "twitter.com")


def is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_jina_first_url(url: str) -> bool:
    host = hostname(url)
    return any(host == expected or host.endswith(f".{expected}") for expected in JINA_FIRST_HOSTS)
```

Create `src/utils/markdown.py`:

```python
from __future__ import annotations

from io import BytesIO
from typing import Any

from markitdown import MarkItDown


class MarkdownConverter:
    def __init__(self, markitdown: Any | None = None) -> None:
        self._markitdown = markitdown or MarkItDown()

    def html_to_markdown(self, html: str, url: str | None = None) -> str:
        stream = BytesIO(html.encode("utf-8"))
        result = self._markitdown.convert_stream(stream, file_extension=".html", url=url)
        return str(result.text_content).strip()
```

Create `src/utils/logging.py`:

```python
from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from src.errors import ProviderError


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def provider_latency_log(
    logger: logging.Logger,
    *,
    provider: str,
    operation: str,
) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    except ProviderError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "provider call failed",
            extra={
                "provider": provider,
                "operation": operation,
                "latency_ms": latency_ms,
                "status": "error",
                "error_type": exc.error_type.value,
                "http_status": exc.http_status,
                "provider_error": exc.safe_repr(),
            },
        )
        raise
    else:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "provider call succeeded",
            extra={
                "provider": provider,
                "operation": operation,
                "latency_ms": latency_ms,
                "status": "ok",
            },
        )
```

- [ ] **Step 5: Run unit tests**

Run:

```bash
uv run pytest tests/unit/test_config.py tests/unit/utils -v
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/config.py src/utils tests/unit/test_config.py tests/unit/utils
git -c user.name=Codex -c user.email=codex@agenteum.com commit --author="Codex <codex@agenteum.com>" -m "feat: add config and utility modules"
```

---

### Task 4: Search Provider Base And Tavily

**Files:**
- Create: `src/providers/search/base.py`
- Create: `src/providers/search/tavily.py`
- Test: `tests/unit/providers/search/test_tavily.py`

- [ ] **Step 1: Write failing Tavily provider tests**

Create `tests/unit/providers/search/test_tavily.py`:

```python
import json

import httpx
import pytest

from src.errors import ErrorType, ProviderError
from src.providers.search.tavily import TavilySearchProvider
from src.schemas import SearchRequest


@pytest.mark.asyncio
async def test_tavily_success_maps_results():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["query"] == "mcp"
        assert body["max_results"] == 5
        assert body["topic"] == "news"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "MCP",
                        "url": "https://example.com/mcp",
                        "content": "Model Context Protocol",
                        "score": 0.8,
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TavilySearchProvider(api_key="key", client=client)

    results = await provider.search(SearchRequest(query="mcp", max_result=5, topic="news"))

    assert results[0].title == "MCP"
    assert results[0].source == "tavily"
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (400, ErrorType.INVALID_REQUEST),
        (401, ErrorType.AUTH_ERROR),
        (403, ErrorType.AUTH_ERROR),
        (429, ErrorType.RATE_LIMITED),
        (432, ErrorType.QUOTA_EXHAUSTED),
        (433, ErrorType.QUOTA_EXHAUSTED),
        (500, ErrorType.PROVIDER_5XX),
    ],
)
async def test_tavily_error_mapping(status_code, error_type):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "provider error"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TavilySearchProvider(api_key="key", client=client)

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == error_type
    await client.aclose()


@pytest.mark.asyncio
async def test_tavily_missing_key_raises_config_error():
    provider = TavilySearchProvider(api_key=None)

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.CONFIG_ERROR
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/providers/search/test_tavily.py -v
```

Expected: fail because `TavilySearchProvider` does not exist.

- [ ] **Step 3: Implement search base protocol**

Create `src/providers/search/base.py`:

```python
from __future__ import annotations

from typing import Protocol

from src.schemas import SearchRequest, SearchResult


class SearchProvider(Protocol):
    name: str

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        raise NotImplementedError
```

- [ ] **Step 4: Implement Tavily provider**

Create `src/providers/search/tavily.py`:

```python
from __future__ import annotations

from typing import Any

import httpx

from src.errors import ErrorType, ProviderError
from src.schemas import SearchRequest, SearchResult

TAVILY_SEARCH_URL = "https://api.tavily.com/search"

_TIME_RANGE_MAP = {
    "day": "day",
    "d": "day",
    "week": "week",
    "w": "week",
    "month": "month",
    "m": "month",
    "year": "year",
    "y": "year",
}

_TOPIC_MAP = {"general": "general", "news": "news", "finance": "finance"}


class TavilySearchProvider:
    name = "tavily"

    def __init__(
        self,
        *,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self.timeout = timeout

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        if not self.api_key:
            raise ProviderError(
                error_type=ErrorType.CONFIG_ERROR,
                provider=self.name,
                message="TAVILY_API_KEY is not configured.",
            )

        payload: dict[str, Any] = {
            "query": request.query,
            "max_results": min(request.max_result, 20),
            "search_depth": "basic",
            "include_answer": False,
        }
        if request.time_range and request.time_range in _TIME_RANGE_MAP:
            payload["time_range"] = _TIME_RANGE_MAP[request.time_range]
        if request.topic and request.topic in _TOPIC_MAP:
            payload["topic"] = _TOPIC_MAP[request.topic]

        try:
            response = await self.client.post(
                TAVILY_SEARCH_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                error_type=ErrorType.TIMEOUT,
                provider=self.name,
                message="Tavily request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                error_type=ErrorType.NETWORK,
                provider=self.name,
                message="Tavily network error.",
            ) from exc

        if response.status_code != 200:
            raise self._error_from_response(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                error_type=ErrorType.INVALID_RESPONSE,
                provider=self.name,
                message="Tavily returned malformed JSON.",
                http_status=response.status_code,
                payload=response.text,
            ) from exc

        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise ProviderError(
                error_type=ErrorType.INVALID_RESPONSE,
                provider=self.name,
                message="Tavily response is missing results list.",
                http_status=response.status_code,
                payload=data,
            )

        return [
            SearchResult(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or ""),
                snippet=item.get("content"),
                published_at=item.get("published_date") or item.get("published_at"),
                source="tavily",
                score=item.get("score"),
            )
            for item in raw_results
            if item.get("url")
        ]

    def _error_from_response(self, response: httpx.Response) -> ProviderError:
        error_type = {
            400: ErrorType.INVALID_REQUEST,
            401: ErrorType.AUTH_ERROR,
            403: ErrorType.AUTH_ERROR,
            429: ErrorType.RATE_LIMITED,
            432: ErrorType.QUOTA_EXHAUSTED,
            433: ErrorType.QUOTA_EXHAUSTED,
        }.get(response.status_code)
        if error_type is None and response.status_code >= 500:
            error_type = ErrorType.PROVIDER_5XX
        if error_type is None:
            error_type = ErrorType.PROVIDER_ERROR
        return ProviderError(
            error_type=error_type,
            provider=self.name,
            message=f"Tavily returned HTTP {response.status_code}.",
            http_status=response.status_code,
            payload=_safe_response_payload(response),
        )


def _safe_response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
```

- [ ] **Step 5: Run Tavily tests**

Run:

```bash
uv run pytest tests/unit/providers/search/test_tavily.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/providers/search/base.py src/providers/search/tavily.py tests/unit/providers/search/test_tavily.py
git -c user.name=Codex -c user.email=codex@agenteum.com commit --author="Codex <codex@agenteum.com>" -m "feat: add tavily search provider"
```

---

### Task 5: Exa And DuckDuckGo Search Providers

**Files:**
- Create: `src/providers/search/exa.py`
- Create: `src/providers/search/duckduckgo.py`
- Test: `tests/unit/providers/search/test_exa.py`
- Test: `tests/unit/providers/search/test_duckduckgo.py`

- [ ] **Step 1: Write failing Exa tests**

Create `tests/unit/providers/search/test_exa.py`:

```python
import json

import httpx
import pytest

from src.errors import ErrorType, ProviderError
from src.providers.search.exa import ExaSearchProvider
from src.schemas import SearchRequest


@pytest.mark.asyncio
async def test_exa_success_maps_results():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["query"] == "mcp"
        assert body["numResults"] == 3
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "MCP",
                        "url": "https://example.com/mcp",
                        "text": "Protocol text",
                        "publishedDate": "2026-05-01",
                        "score": 0.7,
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ExaSearchProvider(api_key="key", client=client)

    results = await provider.search(SearchRequest(query="mcp", max_result=3))

    assert results[0].snippet == "Protocol text"
    assert results[0].source == "exa"
    await client.aclose()


@pytest.mark.asyncio
async def test_exa_budget_error_maps_to_quota_exhausted():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"tag": "NO_MORE_CREDITS", "message": "No credits"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ExaSearchProvider(api_key="key", client=client)

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.QUOTA_EXHAUSTED
    await client.aclose()


@pytest.mark.asyncio
async def test_exa_invalid_key_maps_to_auth_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"tag": "INVALID_API_KEY"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ExaSearchProvider(api_key="key", client=client)

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.AUTH_ERROR
    await client.aclose()
```

- [ ] **Step 2: Write failing DuckDuckGo tests**

Create `tests/unit/providers/search/test_duckduckgo.py`:

```python
import pytest

from src.providers.search.duckduckgo import DuckDuckGoSearchProvider
from src.schemas import SearchRequest


class FakeDDGS:
    def text(self, query, max_results=None, timelimit=None):
        assert query == "mcp"
        assert max_results == 2
        return [
            {
                "title": "MCP",
                "href": "https://example.com/mcp",
                "body": "Duck result",
            }
        ]


@pytest.mark.asyncio
async def test_duckduckgo_success_maps_results():
    provider = DuckDuckGoSearchProvider(ddgs_factory=lambda: FakeDDGS())

    results = await provider.search(SearchRequest(query="mcp", max_result=2))

    assert results[0].url == "https://example.com/mcp"
    assert results[0].snippet == "Duck result"
    assert results[0].source == "duckduckgo"
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/providers/search/test_exa.py tests/unit/providers/search/test_duckduckgo.py -v
```

Expected: fail because Exa and DuckDuckGo providers do not exist.

- [ ] **Step 4: Implement Exa provider**

Create `src/providers/search/exa.py`:

```python
from __future__ import annotations

from typing import Any

import httpx

from src.errors import ErrorType, ProviderError
from src.schemas import SearchRequest, SearchResult

EXA_SEARCH_URL = "https://api.exa.ai/search"

_QUOTA_TAGS = {"NO_MORE_CREDITS", "API_KEY_BUDGET_EXCEEDED", "TEAM_BUDGET_EXCEEDED"}


class ExaSearchProvider:
    name = "exa"

    def __init__(
        self,
        *,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        if not self.api_key:
            raise ProviderError(
                error_type=ErrorType.CONFIG_ERROR,
                provider=self.name,
                message="EXA_API_KEY is not configured.",
            )

        payload: dict[str, Any] = {"query": request.query, "numResults": min(request.max_result, 20)}
        try:
            response = await self.client.post(
                EXA_SEARCH_URL,
                headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                error_type=ErrorType.TIMEOUT,
                provider=self.name,
                message="Exa request timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                error_type=ErrorType.NETWORK,
                provider=self.name,
                message="Exa network error.",
            ) from exc

        if response.status_code != 200:
            raise self._error_from_response(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                error_type=ErrorType.INVALID_RESPONSE,
                provider=self.name,
                message="Exa returned malformed JSON.",
                http_status=response.status_code,
                payload=response.text,
            ) from exc

        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise ProviderError(
                error_type=ErrorType.INVALID_RESPONSE,
                provider=self.name,
                message="Exa response is missing results list.",
                http_status=response.status_code,
                payload=data,
            )

        return [
            SearchResult(
                title=str(item.get("title") or item.get("url") or ""),
                url=str(item.get("url") or ""),
                snippet=item.get("text") or item.get("summary") or _first_highlight(item),
                published_at=item.get("publishedDate") or item.get("published_at"),
                source="exa",
                score=item.get("score"),
            )
            for item in raw_results
            if item.get("url")
        ]

    def _error_from_response(self, response: httpx.Response) -> ProviderError:
        payload = _safe_response_payload(response)
        tag = payload.get("tag") if isinstance(payload, dict) else None
        if response.status_code == 400 or tag == "INVALID_REQUEST_BODY":
            error_type = ErrorType.INVALID_REQUEST
        elif response.status_code == 401 or tag == "INVALID_API_KEY":
            error_type = ErrorType.AUTH_ERROR
        elif response.status_code == 402 and tag in _QUOTA_TAGS:
            error_type = ErrorType.QUOTA_EXHAUSTED
        elif response.status_code == 403:
            error_type = ErrorType.AUTH_ERROR
        elif response.status_code == 429:
            error_type = ErrorType.RATE_LIMITED
        elif response.status_code in {500, 502, 503}:
            error_type = ErrorType.PROVIDER_5XX
        else:
            error_type = ErrorType.PROVIDER_ERROR
        return ProviderError(
            error_type=error_type,
            provider=self.name,
            message=f"Exa returned HTTP {response.status_code}.",
            http_status=response.status_code,
            payload=payload,
        )


def _first_highlight(item: dict[str, Any]) -> str | None:
    highlights = item.get("highlights")
    if isinstance(highlights, list) and highlights:
        return str(highlights[0])
    return None


def _safe_response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
```

- [ ] **Step 5: Implement DuckDuckGo provider**

Create `src/providers/search/duckduckgo.py`:

```python
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from ddgs import DDGS

from src.errors import ErrorType, ProviderError
from src.schemas import SearchRequest, SearchResult

_TIME_RANGE_MAP = {
    "day": "d",
    "d": "d",
    "week": "w",
    "w": "w",
    "month": "m",
    "m": "m",
    "year": "y",
    "y": "y",
}


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    def __init__(self, *, ddgs_factory: Callable[[], Any] = DDGS) -> None:
        self.ddgs_factory = ddgs_factory

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        try:
            return await asyncio.to_thread(self._search_sync, request)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                error_type=ErrorType.PROVIDER_ERROR,
                provider=self.name,
                message="DuckDuckGo search failed.",
                payload={"error": str(exc)},
            ) from exc

    def _search_sync(self, request: SearchRequest) -> list[SearchResult]:
        ddgs = self.ddgs_factory()
        timelimit = _TIME_RANGE_MAP.get(request.time_range or "")
        raw_results = ddgs.text(
            request.query,
            max_results=min(request.max_result, 20),
            timelimit=timelimit,
        )
        return [
            SearchResult(
                title=str(item.get("title") or item.get("href") or ""),
                url=str(item.get("href") or item.get("url") or ""),
                snippet=item.get("body") or item.get("snippet"),
                published_at=None,
                source="duckduckgo",
                score=None,
            )
            for item in raw_results
            if item.get("href") or item.get("url")
        ][: request.max_result]
```

- [ ] **Step 6: Run provider tests**

Run:

```bash
uv run pytest tests/unit/providers/search/test_exa.py tests/unit/providers/search/test_duckduckgo.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/providers/search/exa.py src/providers/search/duckduckgo.py tests/unit/providers/search/test_exa.py tests/unit/providers/search/test_duckduckgo.py
git -c user.name=Codex -c user.email=codex@agenteum.com commit --author="Codex <codex@agenteum.com>" -m "feat: add exa and duckduckgo providers"
```

---

### Task 6: Search Service Fallback

**Files:**
- Create: `src/services/search_service.py`
- Test: `tests/unit/services/test_search_service.py`

- [ ] **Step 1: Write failing search service tests**

Create `tests/unit/services/test_search_service.py`:

```python
import pytest

from src.errors import ErrorType, ProviderError
from src.schemas import SearchRequest, SearchResult
from src.services.search_service import SearchService


class FakeSearchProvider:
    def __init__(self, name, result=None, error_type=None):
        self.name = name
        self.result = result
        self.error_type = error_type
        self.calls = 0

    async def search(self, request):
        self.calls += 1
        if self.error_type:
            raise ProviderError(
                error_type=self.error_type,
                provider=self.name,
                message=f"{self.name} failed",
            )
        return self.result


def result(source):
    return [
        SearchResult(
            title="Title",
            url=f"https://{source}.example",
            snippet=None,
            published_at=None,
            source=source,
            score=None,
        )
    ]


@pytest.mark.asyncio
async def test_tavily_success_stops_chain():
    tavily = FakeSearchProvider("tavily", result("tavily"))
    exa = FakeSearchProvider("exa", result("exa"))
    duckduckgo = FakeSearchProvider("duckduckgo", result("duckduckgo"))
    service = SearchService([tavily, exa, duckduckgo])

    response = await service.search(SearchRequest(query="mcp"))

    assert response.source == "tavily"
    assert exa.calls == 0
    assert duckduckgo.calls == 0


@pytest.mark.asyncio
async def test_quota_exhausted_falls_back_to_exa():
    tavily = FakeSearchProvider("tavily", error_type=ErrorType.QUOTA_EXHAUSTED)
    exa = FakeSearchProvider("exa", result("exa"))
    duckduckgo = FakeSearchProvider("duckduckgo", result("duckduckgo"))
    service = SearchService([tavily, exa, duckduckgo])

    response = await service.search(SearchRequest(query="mcp"))

    assert response.source == "exa"
    assert response.fallbacks[0].from_provider == "tavily"
    assert response.fallbacks[0].to_provider == "exa"
    assert response.fallbacks[0].reason == "quota_exhausted"


@pytest.mark.asyncio
async def test_auth_error_stops_chain():
    tavily = FakeSearchProvider("tavily", error_type=ErrorType.AUTH_ERROR)
    exa = FakeSearchProvider("exa", result("exa"))
    service = SearchService([tavily, exa])

    with pytest.raises(ProviderError) as raised:
        await service.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.AUTH_ERROR
    assert exa.calls == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/services/test_search_service.py -v
```

Expected: fail because `SearchService` does not exist.

- [ ] **Step 3: Implement search service**

Create `src/services/search_service.py`:

```python
from __future__ import annotations

import logging

from src.errors import ErrorType, ProviderError
from src.providers.search.base import SearchProvider
from src.schemas import FallbackRecord, SearchRequest, SearchResponse

FALLBACK_ERROR_TYPES = {
    ErrorType.QUOTA_EXHAUSTED,
    ErrorType.RATE_LIMITED,
    ErrorType.TIMEOUT,
    ErrorType.NETWORK,
    ErrorType.PROVIDER_5XX,
    ErrorType.INVALID_RESPONSE,
}


class SearchService:
    def __init__(
        self,
        providers: list[SearchProvider],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.providers = providers
        self.logger = logger or logging.getLogger(__name__)

    async def search(self, request: SearchRequest) -> SearchResponse:
        fallbacks: list[FallbackRecord] = []
        last_error: ProviderError | None = None

        for index, provider in enumerate(self.providers):
            try:
                results = await provider.search(request)
                return SearchResponse(
                    query=request.query,
                    results=results,
                    source=provider.name,
                    fallbacks=fallbacks,
                )
            except ProviderError as exc:
                last_error = exc
                if exc.error_type not in FALLBACK_ERROR_TYPES or index == len(self.providers) - 1:
                    raise
                next_provider = self.providers[index + 1]
                fallbacks.append(
                    FallbackRecord(
                        from_provider=provider.name,
                        to_provider=next_provider.name,
                        reason=exc.error_type.value,
                    )
                )
                self.logger.info(
                    "search provider fallback",
                    extra={
                        "operation": "search",
                        "from_provider": provider.name,
                        "to_provider": next_provider.name,
                        "reason": exc.error_type.value,
                        "fallback_count": len(fallbacks),
                    },
                )

        if last_error is not None:
            raise last_error
        raise ProviderError(
            error_type=ErrorType.CONFIG_ERROR,
            provider="search_service",
            message="No search providers configured.",
        )
```

- [ ] **Step 4: Run search service tests**

Run:

```bash
uv run pytest tests/unit/services/test_search_service.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/services/search_service.py tests/unit/services/test_search_service.py
git -c user.name=Codex -c user.email=codex@agenteum.com commit --author="Codex <codex@agenteum.com>" -m "feat: add search fallback service"
```

---

### Task 7: HTTP Fetch Provider

**Files:**
- Create: `src/providers/fetch/base.py`
- Create: `src/providers/fetch/http.py`
- Test: `tests/unit/providers/fetch/test_http_fetch.py`

- [ ] **Step 1: Write failing HTTP fetch provider tests**

Create `tests/unit/providers/fetch/test_http_fetch.py`:

```python
import httpx
import pytest

from src.errors import ErrorType, ProviderError
from src.providers.fetch.http import HttpFetchProvider


class FakeMarkdownConverter:
    def html_to_markdown(self, html, url=None):
        assert "<h1>Hello</h1>" in html
        assert url == "https://example.com/"
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/providers/fetch/test_http_fetch.py -v
```

Expected: fail because fetch provider modules do not exist.

- [ ] **Step 3: Implement fetch base protocol**

Create `src/providers/fetch/base.py`:

```python
from __future__ import annotations

from typing import Protocol

from src.schemas import FetchResult


class FetchProvider(Protocol):
    name: str

    async def fetch(self, url: str) -> FetchResult:
        raise NotImplementedError
```

- [ ] **Step 4: Implement HTTP fetch provider**

Create `src/providers/fetch/http.py`:

```python
from __future__ import annotations

import httpx

from src.errors import ErrorType, ProviderError
from src.schemas import FetchResult
from src.utils.content_detection import looks_blocked
from src.utils.headers import get_fetch_headers
from src.utils.markdown import MarkdownConverter

MIN_MARKDOWN_LENGTH = 20


class HttpFetchProvider:
    name = "http"

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
```

- [ ] **Step 5: Run HTTP fetch tests**

Run:

```bash
uv run pytest tests/unit/providers/fetch/test_http_fetch.py -v
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/providers/fetch/base.py src/providers/fetch/http.py tests/unit/providers/fetch/test_http_fetch.py
git -c user.name=Codex -c user.email=codex@agenteum.com commit --author="Codex <codex@agenteum.com>" -m "feat: add http fetch provider"
```

---

### Task 8: Jina Provider And Fetch Service

**Files:**
- Create: `src/providers/fetch/jina.py`
- Create: `src/services/fetch_service.py`
- Test: `tests/unit/providers/fetch/test_jina_fetch.py`
- Test: `tests/unit/services/test_fetch_service.py`

- [ ] **Step 1: Write failing Jina provider tests**

Create `tests/unit/providers/fetch/test_jina_fetch.py`:

```python
import httpx
import pytest

from src.errors import ErrorType, ProviderError
from src.providers.fetch.jina import JinaFetchProvider


@pytest.mark.asyncio
async def test_jina_success_returns_markdown():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer key"
        assert str(request.url) == "https://r.jina.ai/https://example.com/"
        return httpx.Response(200, text="# Example")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = JinaFetchProvider(api_key="key", client=client)

    result = await provider.fetch("https://example.com/")

    assert result.source == "jina"
    assert result.content == "# Example"
    await client.aclose()


@pytest.mark.asyncio
async def test_jina_missing_key_raises_config_error():
    provider = JinaFetchProvider(api_key=None)

    with pytest.raises(ProviderError) as raised:
        await provider.fetch("https://example.com/")

    assert raised.value.error_type == ErrorType.CONFIG_ERROR
```

- [ ] **Step 2: Write failing fetch service tests**

Create `tests/unit/services/test_fetch_service.py`:

```python
import pytest

from src.errors import ErrorType, ProviderError
from src.schemas import FetchResult
from src.services.fetch_service import FetchService


class FakeFetchProvider:
    def __init__(self, name, result=None, error_type=None):
        self.name = name
        self.result = result
        self.error_type = error_type
        self.calls = []

    async def fetch(self, url):
        self.calls.append(url)
        if self.error_type:
            raise ProviderError(
                error_type=self.error_type,
                provider=self.name,
                message=f"{self.name} failed",
            )
        return self.result or FetchResult(
            url=url,
            final_url=url,
            content=f"# {self.name}",
            source=self.name,
            status="ok",
            error=None,
        )


@pytest.mark.asyncio
async def test_x_url_routes_directly_to_jina():
    http = FakeFetchProvider("http")
    jina = FakeFetchProvider("jina")
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://x.com/openai/status/1"])

    assert response.results[0].source == "jina"
    assert http.calls == []


@pytest.mark.asyncio
async def test_blocked_http_falls_back_to_jina():
    http = FakeFetchProvider("http", error_type=ErrorType.BLOCKED)
    jina = FakeFetchProvider("jina")
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://example.com"])

    assert response.results[0].source == "jina"
    assert jina.calls == ["https://example.com"]


@pytest.mark.asyncio
async def test_unsupported_content_returns_item_error_without_jina():
    http = FakeFetchProvider("http", error_type=ErrorType.UNSUPPORTED_CONTENT)
    jina = FakeFetchProvider("jina")
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://example.com/a.pdf"])

    assert response.results[0].status == "error"
    assert response.results[0].error.type == "unsupported_content"
    assert jina.calls == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/providers/fetch/test_jina_fetch.py tests/unit/services/test_fetch_service.py -v
```

Expected: fail because Jina provider and fetch service do not exist.

- [ ] **Step 4: Implement Jina provider**

Create `src/providers/fetch/jina.py`:

```python
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
```

- [ ] **Step 5: Implement fetch service**

Create `src/services/fetch_service.py`:

```python
from __future__ import annotations

import asyncio
import logging

from src.errors import ErrorType, ProviderError
from src.providers.fetch.base import FetchProvider
from src.schemas import FetchError, FetchResponse, FetchResult
from src.utils.urls import is_jina_first_url

HTTP_TO_JINA_FALLBACK_ERRORS = {
    ErrorType.BLOCKED,
    ErrorType.EMPTY_CONTENT,
    ErrorType.TIMEOUT,
    ErrorType.NETWORK,
    ErrorType.PROVIDER_5XX,
    ErrorType.INVALID_RESPONSE,
}


class FetchService:
    def __init__(
        self,
        *,
        http_provider: FetchProvider,
        jina_provider: FetchProvider,
        logger: logging.Logger | None = None,
    ) -> None:
        self.http_provider = http_provider
        self.jina_provider = jina_provider
        self.logger = logger or logging.getLogger(__name__)

    async def fetch(self, urls: list[str]) -> FetchResponse:
        results = await asyncio.gather(*(self._fetch_one(url) for url in urls))
        return FetchResponse(results=list(results))

    async def _fetch_one(self, url: str) -> FetchResult:
        if is_jina_first_url(url):
            return await self._fetch_with_item_error(self.jina_provider, url)

        try:
            return await self.http_provider.fetch(url)
        except ProviderError as exc:
            if exc.error_type in HTTP_TO_JINA_FALLBACK_ERRORS:
                self.logger.info(
                    "fetch provider fallback",
                    extra={
                        "operation": "fetch",
                        "from_provider": "http",
                        "to_provider": "jina",
                        "reason": exc.error_type.value,
                        "fallback_count": 1,
                    },
                )
                return await self._fetch_with_item_error(self.jina_provider, url)
            return self._error_result(url, "http", exc)

    async def _fetch_with_item_error(self, provider: FetchProvider, url: str) -> FetchResult:
        try:
            return await provider.fetch(url)
        except ProviderError as exc:
            return self._error_result(url, provider.name, exc)

    def _error_result(self, url: str, provider_name: str, exc: ProviderError) -> FetchResult:
        return FetchResult(
            url=url,
            final_url=None,
            content=None,
            source=provider_name,
            status="error",
            error=FetchError(
                type=exc.error_type.value,
                message=exc.message,
                provider=provider_name,
            ),
        )
```

- [ ] **Step 6: Run Jina and fetch service tests**

Run:

```bash
uv run pytest tests/unit/providers/fetch/test_jina_fetch.py tests/unit/services/test_fetch_service.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/providers/fetch/jina.py src/services/fetch_service.py tests/unit/providers/fetch/test_jina_fetch.py tests/unit/services/test_fetch_service.py
git -c user.name=Codex -c user.email=codex@agenteum.com commit --author="Codex <codex@agenteum.com>" -m "feat: add jina provider and fetch service"
```

---

### Task 9: MCP Resources And Tool Registration

**Files:**
- Create: `src/resources/search-guide.md`
- Create: `src/resources/fetch-guide.md`
- Create: `src/resources/providers-capabilities.md`
- Create: `src/resources/tool_guides.py`
- Create: `src/api/mcp_full.py`
- Test: `tests/unit/api/test_mcp_full.py`

- [ ] **Step 1: Write failing API/resource tests**

Create `tests/unit/api/test_mcp_full.py`:

```python
import pytest

from src.api.mcp_full import create_mcp_server
from src.resources.tool_guides import load_resource_text
from src.schemas import SearchResponse


def test_resource_markdown_files_load():
    assert "agenteum_search" in load_resource_text("search-guide.md")
    assert "agenteum_fetch" in load_resource_text("fetch-guide.md")
    assert "Tavily" in load_resource_text("providers-capabilities.md")


@pytest.mark.asyncio
async def test_mcp_server_can_be_created_with_fake_services():
    class FakeSearchService:
        async def search(self, request):
            return SearchResponse(query=request.query, results=[], source="duckduckgo", fallbacks=[])

    class FakeFetchService:
        async def fetch(self, urls):
            from src.schemas import FetchResponse

            return FetchResponse(results=[])

    mcp = create_mcp_server(search_service=FakeSearchService(), fetch_service=FakeFetchService())

    assert mcp.name == "Agenteum Net"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/api/test_mcp_full.py -v
```

Expected: fail because API/resource modules and Markdown files do not exist.

- [ ] **Step 3: Add resource Markdown files**

Create `src/resources/search-guide.md`:

```markdown
# agenteum_search

Use `agenteum_search` to discover relevant web pages for a query.

Parameters:

- `query`: required search query.
- `max_result`: result count from 1 to 20, default 10.
- `time_range`: best-effort value among `day`, `week`, `month`, `year`, `d`, `w`, `m`, and `y`.
- `topic`: best-effort topic hint. Tavily supports `general`, `news`, and `finance`.

Provider fallback order is Tavily, then Exa, then DuckDuckGo.
```

Create `src/resources/fetch-guide.md`:

```markdown
# agenteum_fetch

Use `agenteum_fetch` to read known HTTP or HTTPS URLs as Markdown.

Parameters:

- `urls`: 1 to 10 URLs.

The tool returns one result item per input URL. Individual failures are reported in the matching result item and do not fail the whole batch.

`x.com` and `twitter.com` URLs go directly to Jina. Other URLs use HTTP fetch first and fall back to Jina when the HTTP result appears blocked, empty, timed out, or otherwise unavailable.
```

Create `src/resources/providers-capabilities.md`:

```markdown
# Provider Capabilities

Search providers:

- Tavily: API key required, first search provider.
- Exa: API key required, search fallback provider.
- DuckDuckGo: no API key, free fallback provider through `ddgs`.

Fetch providers:

- HTTP: first provider for normal HTML pages, converts HTML to Markdown with MarkItDown.
- Jina: direct provider for x.com/twitter.com and fallback provider for blocked or empty HTTP fetches.

Required environment variables:

- `TAVILY_API_KEY`
- `EXA_API_KEY`
- `JINA_API_KEY`
```

- [ ] **Step 4: Implement resource loader**

Create `src/resources/tool_guides.py`:

```python
from __future__ import annotations

from importlib.resources import files

RESOURCE_URIS = {
    "agenteum://tools/search-guide": "search-guide.md",
    "agenteum://tools/fetch-guide": "fetch-guide.md",
    "agenteum://providers/capabilities": "providers-capabilities.md",
}


def load_resource_text(filename: str) -> str:
    return files("src.resources").joinpath(filename).read_text(encoding="utf-8")


def resource_text_by_uri(uri: str) -> str:
    return load_resource_text(RESOURCE_URIS[uri])
```

- [ ] **Step 5: Implement MCP full server registration**

Create `src/api/mcp_full.py`:

```python
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from src.resources.tool_guides import RESOURCE_URIS, resource_text_by_uri
from src.schemas import FetchRequest, SearchRequest


def create_mcp_server(*, search_service: Any, fetch_service: Any) -> FastMCP:
    mcp = FastMCP(
        "Agenteum Net",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    @mcp.tool()
    async def agenteum_search(
        query: str,
        max_result: int = 10,
        time_range: str | None = None,
        topic: str | None = None,
    ) -> dict:
        """Search the web through Tavily, Exa, and DuckDuckGo fallback providers."""
        request = SearchRequest(
            query=query,
            max_result=max_result,
            time_range=time_range,
            topic=topic,
        )
        response = await search_service.search(request)
        return response.model_dump(by_alias=True)

    @mcp.tool()
    async def agenteum_fetch(urls: list[str]) -> dict:
        """Fetch known URLs as Markdown. Returns one result item per URL."""
        request = FetchRequest(urls=urls)
        response = await fetch_service.fetch(request.normalized_urls())
        return response.model_dump()

    for uri in RESOURCE_URIS:

        @mcp.resource(uri)
        def read_resource(uri: str = uri) -> str:
            return resource_text_by_uri(uri)

    return mcp
```

- [ ] **Step 6: Run API/resource tests**

Run:

```bash
uv run pytest tests/unit/api/test_mcp_full.py -v
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/resources src/api/mcp_full.py tests/unit/api/test_mcp_full.py
git -c user.name=Codex -c user.email=codex@agenteum.com commit --author="Codex <codex@agenteum.com>" -m "feat: register mcp tools and resources"
```

---

### Task 10: Transport, App Wiring, Smoke Tests, And Docs

**Files:**
- Create: `src/api/transport.py`
- Create: `src/app.py`
- Create: `tests/smoke/test_mcp_http.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing app smoke tests**

Create `tests/smoke/test_mcp_http.py`:

```python
from src.app import create_app


def test_create_app_mounts_mcp_endpoint():
    app = create_app()

    paths = {route.path for route in app.routes}

    assert "/mcp/full" in paths or any(path.startswith("/mcp/full") for path in paths)
```

- [ ] **Step 2: Run smoke test to verify it fails**

Run:

```bash
uv run pytest tests/smoke/test_mcp_http.py -v
```

Expected: fail because `src.app` and `src.api.transport` do not exist.

- [ ] **Step 3: Implement transport mounting**

Create `src/api/transport.py`:

```python
from __future__ import annotations

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP


def mount_mcp_streamable_http(app: FastAPI, *, mcp: FastMCP, path: str = "/mcp/full") -> None:
    app.mount(path, mcp.streamable_http_app())
```

- [ ] **Step 4: Implement app wiring**

Create `src/app.py`:

```python
from __future__ import annotations

import logging

import httpx
import uvicorn
from fastapi import FastAPI

from src.api.mcp_full import create_mcp_server
from src.api.transport import mount_mcp_streamable_http
from src.config import Settings, get_settings
from src.providers.fetch.http import HttpFetchProvider
from src.providers.fetch.jina import JinaFetchProvider
from src.providers.search.duckduckgo import DuckDuckGoSearchProvider
from src.providers.search.exa import ExaSearchProvider
from src.providers.search.tavily import TavilySearchProvider
from src.services.fetch_service import FetchService
from src.services.search_service import SearchService
from src.utils.markdown import MarkdownConverter


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logger = logging.getLogger("agenteum_net")
    settings.validate_network_binding(logger)

    app = FastAPI(title="Agenteum Net")

    search_client = httpx.AsyncClient(timeout=settings.request_timeout)
    fetch_client = httpx.AsyncClient(timeout=settings.fetch_timeout, follow_redirects=True)
    jina_client = httpx.AsyncClient(timeout=settings.jina_timeout)

    search_service = SearchService(
        [
            TavilySearchProvider(api_key=settings.tavily_api_key, client=search_client),
            ExaSearchProvider(api_key=settings.exa_api_key, client=search_client),
            DuckDuckGoSearchProvider(),
        ],
        logger=logger,
    )
    fetch_service = FetchService(
        http_provider=HttpFetchProvider(
            client=fetch_client,
            converter=MarkdownConverter(),
        ),
        jina_provider=JinaFetchProvider(api_key=settings.jina_api_key, client=jina_client),
        logger=logger,
    )

    mcp = create_mcp_server(search_service=search_service, fetch_service=fetch_service)
    mount_mcp_streamable_http(app, mcp=mcp, path="/mcp/full")
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port)
```

- [ ] **Step 5: Update README run instructions**

Modify `README.md` so it includes:

```markdown
## Development Checks

```bash
uv run pytest
uv run ruff check .
```

## Security

Agenteum Net v1.0 has no authentication. The default host is `127.0.0.1`. Setting `AGENTEUM_HOST=0.0.0.0` requires `AGENTEUM_ALLOW_REMOTE=true` and is only intended for trusted local or WSL setups.
```

- [ ] **Step 6: Run smoke and full test suite**

Run:

```bash
uv run pytest -v
uv run ruff check .
```

Expected: all tests pass and ruff reports no errors.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/api/transport.py src/app.py tests/smoke/test_mcp_http.py README.md
git -c user.name=Codex -c user.email=codex@agenteum.com commit --author="Codex <codex@agenteum.com>" -m "feat: wire mcp http app"
```

---

### Task 11: Final Verification And Manual Notes

**Files:**
- Modify: `README.md`
- No implementation files unless verification reveals a concrete issue.

- [ ] **Step 1: Run complete verification**

Run:

```bash
uv run pytest -v
uv run ruff check .
git status --short --branch
```

Expected:

- pytest exits 0.
- ruff exits 0.
- `git status --short --branch` shows only expected documentation edits before the final commit.

- [ ] **Step 2: Add manual smoke command notes**

Append this section to `README.md`:

```markdown
## Manual Provider Smoke Checks

Default automated tests do not call real Tavily, Exa, Jina, or DuckDuckGo endpoints.

After placing real keys in `.env`, start the server:

```bash
uv run agenteum-net
```

Then connect an MCP client to:

```text
http://127.0.0.1:8765/mcp/full
```

Run one search query and one fetch request manually to validate local provider credentials.
```

- [ ] **Step 3: Commit final docs**

Run:

```bash
git add README.md
git -c user.name=Codex -c user.email=codex@agenteum.com commit --author="Codex <codex@agenteum.com>" -m "docs: add manual smoke instructions"
```

- [ ] **Step 4: Report final state**

Run:

```bash
git log --oneline -5
git status --short --branch
```

Expected:

- Recent commits include all implementation tasks.
- Working tree is clean.

---

## Self-Review Checklist

- Spec coverage:
  - HTTP-only MCP endpoint `/mcp/full`: Task 9 and Task 10.
  - `agenteum_search`: Task 9.
  - `agenteum_fetch`: Task 9.
  - Tavily, Exa, DuckDuckGo providers: Task 4 and Task 5.
  - HTTP and Jina fetch providers: Task 7 and Task 8.
  - `.env` configuration and remote binding safety: Task 1 and Task 3.
  - Unified schemas: Task 2.
  - Provider errors and safe logging: Task 2 and Task 3.
  - Search fallback: Task 6.
  - Fetch routing/fallback/partial failure: Task 8.
  - Markdown resources: Task 9.
  - TDD and smoke tests: every task includes failing test, implementation, verification, and commit.
- Placeholder scan:
  - This plan avoids unspecified implementation steps and gives exact file paths, commands, and expected outcomes.
- Type consistency:
  - Service methods use `SearchRequest`, `SearchResponse`, `FetchResponse`, and `FetchResult` as defined in Task 2.
  - Provider errors use `ErrorType` and `ProviderError` from Task 2.
  - API registration calls `SearchService.search()` and `FetchService.fetch()` with the exact signatures defined in Tasks 6 and 8.
