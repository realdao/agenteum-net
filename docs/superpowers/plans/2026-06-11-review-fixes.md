# Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the high-confidence review findings from `docs/review/` without pulling disputed items into the first repair batch.

**Architecture:** Keep the existing provider/service/API split. Providers continue to translate external APIs into unified schemas and `ProviderError`; services own fallback and batching policy; `src/app.py` owns runtime wiring and provider enablement; MCP tool signatures expose constraints that already exist in `src/schemas.py`.

**Tech Stack:** Python 3.11+, uv, FastAPI, FastMCP, httpx, Pydantic v2, pytest, pytest-asyncio, ruff.

---

## References

- Review reports: `docs/review/260611-claude-review-report.md`, `docs/review/260611-claude-review-report-2.md`, `docs/review/260611-kimi-review-report.md`
- Repository rules: `AGENTS.md`, `rules/code-philosophy.md`, `rules/git-commit-standards.md`
- Commit command examples in this plan use Codex identity. If another agent executes a task, use that agent's name and email according to `rules/git-commit-standards.md`.

## Scope

Implement these high-confidence fixes:

- Fetch robustness: item-level Jina failures, conservative blocked-page detection, and HTTP 4xx error signaling.
- Search robustness: skip unconfigured paid providers at app wiring, request Exa snippets, and de-duplicate requested parallel providers.
- MCP schema visibility: expose `time_range`, `max_result`, `providers`, and `urls` constraints through tool signatures.
- E2E hygiene: mark e2e tests, exclude them by default, stop killing fixed-port processes, use a free port, perform real readiness polling, and drain or redirect server logs.
- Small operational fixes: close app-owned httpx clients, add timestamps to logs, and validate `search-eval --providers` early.

Do not implement these disputed or deferred items in this plan:

- Jina Reader URL encoding by quoting the whole URL. Jina's documented public pattern prepends the target URL; this needs separate real-provider verification before changing.
- Provider-owned `AsyncClient` async context managers. The app path injects shared clients; provider-local ownership can be a later cleanup.
- `parallel_search` `CancelledError` handling. The review claim needs a reproduction before changing cancellation semantics.
- SSRF/private network filtering, fetch size limits, MarkItDown `to_thread`, deployment hardening, package rename, or locale configuration. These are valid candidates for later plans but are outside this first repair batch.

## File Map

- `src/services/fetch_service.py`: preserve one result per URL, convert Jina config/auth and unexpected failures into item errors, and avoid Jina fallback for HTTP 4xx item errors.
- `src/utils/content_detection.py`: stop scanning full raw HTML for blocked markers; use title and converted markdown with short-content guards.
- `src/providers/fetch/http.py`: map HTTP 4xx HTML pages to `ProviderError` instead of parsing them as successful page content.
- `src/schemas.py`: add optional HTTP status to fetch item errors, and reuse existing search/fetch constraints.
- `src/app.py`: skip unconfigured Tavily/Exa providers, keep DuckDuckGo, close app-owned clients during lifespan shutdown, and configure timestamped logging.
- `src/providers/search/exa.py`: request text contents so Exa results include snippets.
- `src/services/search_service.py`: de-duplicate `provider_names` while preserving order.
- `src/api/mcp_full.py`: move schema constraints into MCP tool signatures using `Annotated`, `Field`, `TimeRange`, and `SearchProviderName`.
- `tests/unit/services/test_fetch_service.py`: add batch partial-failure and HTTP 4xx fallback-policy tests.
- `tests/unit/utils/test_content_detection.py`: add raw-noscript, article, and html-only title regression tests.
- `tests/unit/providers/fetch/test_http_fetch.py`: add HTTP 4xx provider test.
- `tests/unit/test_schemas.py`: add fetch error HTTP status serialization test if the schema changes.
- `tests/unit/test_app.py`: add provider-wiring, lifespan close, and logging-format tests.
- `tests/unit/providers/search/test_exa.py`: assert Exa request includes `contents`.
- `tests/unit/services/test_search_service.py`: add duplicate provider-name test.
- `tests/unit/api/test_mcp_full.py`: assert generated FastMCP tool schemas include constraints.
- `tests/e2e/test_opencode_mcp.py`: mark e2e tests and replace fixed-port/process-kill startup.
- `pyproject.toml`: exclude e2e by default and register the marker.
- `src/evaluation/search_eval.py`: validate provider names before execution.
- `tests/unit/evaluation/test_search_eval.py`: add unknown-provider validation test.

---

### Task 1: Fetch Item Errors, Blocked Detection, And HTTP 4xx

**Files:**
- Modify: `src/services/fetch_service.py`
- Modify: `src/utils/content_detection.py`
- Modify: `src/providers/fetch/http.py`
- Modify: `src/schemas.py`
- Test: `tests/unit/services/test_fetch_service.py`
- Test: `tests/unit/utils/test_content_detection.py`
- Test: `tests/unit/providers/fetch/test_http_fetch.py`
- Test: `tests/unit/test_schemas.py`

- [ ] **Step 1: Write failing fetch service tests**

Add these tests to `tests/unit/services/test_fetch_service.py`:

```python
class RaisingFetchProvider:
    def __init__(self, name, error_type):
        self.name = name
        self.error_type = error_type
        self.calls = []

    async def fetch(self, url):
        self.calls.append(url)
        raise ProviderError(
            error_type=self.error_type,
            provider=self.name,
            message=f"{self.name} failed",
            http_status=404 if self.error_type == ErrorType.INVALID_RESPONSE else None,
        )


@pytest.mark.asyncio
async def test_jina_config_error_is_returned_as_item_error_instead_of_failing_batch():
    http = FakeFetchProvider("http")
    jina = RaisingFetchProvider("jina", ErrorType.CONFIG_ERROR)
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://example.com", "https://x.com/openai/status/1"])

    assert [item.status for item in response.results] == ["ok", "error"]
    assert response.results[0].source == "http"
    assert response.results[1].source == "jina"
    assert response.results[1].error.type == "config_error"


@pytest.mark.asyncio
async def test_http_4xx_invalid_response_does_not_fallback_to_jina():
    http = RaisingFetchProvider("http", ErrorType.INVALID_RESPONSE)
    jina = FakeFetchProvider("jina")
    service = FetchService(http_provider=http, jina_provider=jina)

    response = await service.fetch(["https://example.com/missing"])

    assert response.results[0].status == "error"
    assert response.results[0].source == "http"
    assert response.results[0].error.type == "invalid_response"
    assert response.results[0].error.http_status == 404
    assert jina.calls == []
```

- [ ] **Step 2: Write failing blocked-detection tests**

Add these tests to `tests/unit/utils/test_content_detection.py`:

```python
def test_blocked_detector_ignores_noscript_spa_marker_in_raw_html():
    html = """
    <html>
      <head><title>Product App</title></head>
      <body><noscript>You need to enable JavaScript to run this app.</noscript></body>
    </html>
    """

    assert not looks_blocked(html)


def test_blocked_detector_ignores_cloudflare_title_before_markdown_exists():
    html = "<html><head><title>Cloudflare architecture notes</title></head><body></body></html>"

    assert not looks_blocked(html)


def test_blocked_detector_ignores_long_article_that_mentions_captcha():
    html = "<title>How to Build a CAPTCHA System</title>"
    markdown = "# How to Build a CAPTCHA System\n\n" + ("ordinary article content " * 80)

    assert not looks_blocked(html, markdown)
```

- [ ] **Step 3: Write failing HTTP 4xx provider test**

Add this test to `tests/unit/providers/fetch/test_http_fetch.py`:

```python
@pytest.mark.asyncio
async def test_http_fetch_4xx_raises_invalid_response_with_status():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            headers={"Content-Type": "text/html"},
            content=b"<html><body><h1>Not Found</h1></body></html>",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HttpFetchProvider(client=client, converter=FakeMarkdownConverter())

    with pytest.raises(ProviderError) as raised:
        await provider.fetch("https://example.com/missing")

    assert raised.value.error_type == ErrorType.INVALID_RESPONSE
    assert raised.value.http_status == 404
    await client.aclose()
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/services/test_fetch_service.py tests/unit/utils/test_content_detection.py tests/unit/providers/fetch/test_http_fetch.py -v
```

Expected: fail because Jina config/auth errors still escape the batch, raw HTML blocked markers still match, and HTTP 4xx still parses as content.

- [ ] **Step 5: Add HTTP status to fetch item errors**

Modify `src/schemas.py`:

```python
class FetchError(BaseModel):
    type: str
    message: str
    provider: FetchProviderName
    http_status: int | None = None
```

Add this test to `tests/unit/test_schemas.py`:

```python
def test_fetch_error_can_serialize_http_status():
    item = FetchResult(
        url="https://example.com/missing",
        final_url=None,
        content=None,
        source="http",
        status="error",
        error={
            "type": "invalid_response",
            "message": "HTTP fetch returned 404.",
            "provider": "http",
            "http_status": 404,
        },
    )

    assert item.model_dump()["error"]["http_status"] == 404
```

- [ ] **Step 6: Convert fetch failures to item errors**

Modify `src/services/fetch_service.py` so `fetch()` uses `return_exceptions=True`, `_fetch_with_item_error()` no longer re-raises config/auth errors, and the HTTP-to-Jina policy is guarded by a helper:

```python
async def fetch(self, urls: list[str]) -> FetchResponse:
    raw_results = await asyncio.gather(
        *(self._fetch_one(url) for url in urls),
        return_exceptions=True,
    )
    results: list[FetchResult] = []
    for url, result in zip(urls, raw_results, strict=True):
        if isinstance(result, FetchResult):
            results.append(result)
            continue
        if isinstance(result, ProviderError):
            results.append(self._error_result(url, _fetch_provider_name(result.provider), result))
            continue
        results.append(
            self._error_result(
                url,
                "http",
                ProviderError(
                    error_type=ErrorType.PROVIDER_ERROR,
                    provider="http",
                    message="Unexpected fetch error.",
                    payload={"error": str(result)},
                ),
            )
        )
    return FetchResponse(results=results)

def _should_fallback_to_jina(exc: ProviderError) -> bool:
    if (
        exc.error_type == ErrorType.INVALID_RESPONSE
        and exc.http_status is not None
        and 400 <= exc.http_status < 500
    ):
        return False
    return exc.error_type in HTTP_TO_JINA_FALLBACK_ERRORS

def _fetch_provider_name(provider: str) -> FetchProviderName:
    return provider if provider in {"http", "jina"} else "http"
```

Update `_fetch_one()` to call `_should_fallback_to_jina(exc)`. Update `_error_result()` to pass `http_status=exc.http_status` into `FetchError`.

- [ ] **Step 7: Make blocked detection conservative**

Modify `src/utils/content_detection.py` so raw HTML body is not scanned. Keep title extraction. A minimal implementation is:

```python
def looks_blocked(html: str, markdown: str | None = None) -> bool:
    title = extract_title(html).lower()
    markdown_text = markdown or ""
    markdown_lower = markdown_text.lower()
    short_markdown = len(markdown_text.strip()) < 500

    if any(marker in title for marker in STRONG_BLOCKED_MARKERS):
        return True
    if markdown is not None and short_markdown:
        if any(marker in markdown_lower for marker in STRONG_BLOCKED_MARKERS):
            return True
    return (
        markdown is not None
        and short_markdown
        and any(marker in title for marker in WEAK_BLOCKED_MARKERS)
    )
```

Keep the existing captcha test in `tests/unit/utils/test_content_detection.py`; it already puts the marker in the title and short converted markdown:

```python
def test_blocked_detector_flags_captcha_page():
    assert looks_blocked("<title>Captcha</title>", "Verify you are human")
```

- [ ] **Step 8: Reject HTTP 4xx before Markdown conversion**

Modify `src/providers/fetch/http.py` before the content-type check:

```python
if 400 <= response.status_code < 500:
    raise ProviderError(
        error_type=ErrorType.INVALID_RESPONSE,
        provider=self.name,
        message=f"HTTP fetch returned {response.status_code}.",
        http_status=response.status_code,
        payload=response.text,
    )
```

- [ ] **Step 9: Run fetch-focused verification**

Run:

```bash
uv run pytest tests/unit/services/test_fetch_service.py tests/unit/utils/test_content_detection.py tests/unit/providers/fetch/test_http_fetch.py tests/unit/test_schemas.py -v
uv run ruff check src/services/fetch_service.py src/utils/content_detection.py src/providers/fetch/http.py src/schemas.py tests/unit/services/test_fetch_service.py tests/unit/utils/test_content_detection.py tests/unit/providers/fetch/test_http_fetch.py tests/unit/test_schemas.py
```

Expected: all selected tests and ruff pass.

- [ ] **Step 10: Commit**

```bash
git add src/services/fetch_service.py src/utils/content_detection.py src/providers/fetch/http.py src/schemas.py tests/unit/services/test_fetch_service.py tests/unit/utils/test_content_detection.py tests/unit/providers/fetch/test_http_fetch.py tests/unit/test_schemas.py
git commit --author="Codex <codex@agenteum.com>" -m "fix: harden fetch item errors"
```

---

### Task 2: Search Provider Wiring, Exa Snippets, And Parallel Selection

**Files:**
- Modify: `src/app.py`
- Modify: `src/providers/search/exa.py`
- Modify: `src/services/search_service.py`
- Test: `tests/unit/test_app.py`
- Test: `tests/unit/providers/search/test_exa.py`
- Test: `tests/unit/services/test_search_service.py`

- [ ] **Step 1: Write failing app provider-wiring tests**

Add to `tests/unit/test_app.py`:

```python
import httpx
import pytest

from src.app import _build_search_providers


@pytest.mark.asyncio
async def test_build_search_providers_skips_unconfigured_paid_providers():
    client = httpx.AsyncClient()
    try:
        providers = _build_search_providers(Settings(), client, logging.getLogger("test"))
    finally:
        await client.aclose()

    assert [provider.name for provider in providers] == ["duckduckgo"]


@pytest.mark.asyncio
async def test_build_search_providers_keeps_configured_tavily_and_duckduckgo():
    client = httpx.AsyncClient()
    try:
        providers = _build_search_providers(
            Settings(TAVILY_API_KEY="tavily-key"),
            client,
            logging.getLogger("test"),
        )
    finally:
        await client.aclose()

    assert [provider.name for provider in providers] == ["tavily", "duckduckgo"]
```

- [ ] **Step 2: Write failing Exa request test**

In `tests/unit/providers/search/test_exa.py`, extend the handler in `test_exa_success_maps_results()`:

```python
assert body["contents"] == {"text": {"maxCharacters": 500}}
```

Also add a response item that resembles the real Exa default shape to document why contents matters:

```python
{
    "title": "MCP without text",
    "url": "https://example.com/no-text",
    "publishedDate": "2026-05-02",
    "score": 0.4,
}
```

Assert that the first result with text still maps a snippet, and the no-text result has `snippet is None`.

- [ ] **Step 3: Write failing duplicate-provider test**

Add to `tests/unit/services/test_search_service.py`:

```python
@pytest.mark.asyncio
async def test_parallel_search_deduplicates_requested_provider_names():
    tavily = FakeSearchProvider("tavily", result("tavily"))
    service = SearchService([tavily])

    response = await service.parallel_search(
        SearchRequest(query="mcp"),
        provider_names=["tavily", "tavily"],
    )

    assert tavily.calls == 1
    assert response.sources == ["tavily"]
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_app.py tests/unit/providers/search/test_exa.py tests/unit/services/test_search_service.py -v
```

Expected: fail because the app always wires Tavily/Exa, Exa payload lacks `contents`, and duplicate provider names call the same provider twice.

- [ ] **Step 5: Add provider-wiring helper**

Modify `src/app.py`:

```python
def _build_search_providers(
    settings: Settings,
    search_client: httpx.AsyncClient,
    logger: logging.Logger,
) -> list:
    providers = []
    if settings.tavily_api_key:
        providers.append(
            TavilySearchProvider(api_key=settings.tavily_api_key, client=search_client)
        )
    else:
        logger.info("Tavily search disabled: TAVILY_API_KEY is not configured.")
    if settings.exa_api_key:
        providers.append(ExaSearchProvider(api_key=settings.exa_api_key, client=search_client))
    else:
        logger.info("Exa search disabled: EXA_API_KEY is not configured.")
    providers.append(DuckDuckGoSearchProvider())
    return providers
```

Then change `create_app()` to pass `_build_search_providers(settings, search_client, logger)` into `SearchService`.

- [ ] **Step 6: Request Exa text contents**

Modify `src/providers/search/exa.py` payload:

```python
payload: dict[str, Any] = {
    "query": request.query,
    "numResults": min(request.max_result, 20),
    "contents": {"text": {"maxCharacters": 500}},
}
```

- [ ] **Step 7: De-duplicate requested parallel providers**

Modify `_select_parallel_providers()` in `src/services/search_service.py`:

```python
seen_provider_names: set[str] = set()
for provider_name in provider_names:
    if provider_name in seen_provider_names:
        continue
    seen_provider_names.add(provider_name)
    provider = providers_by_name.get(provider_name)
    if provider is None:
        raise ProviderError(
            error_type=ErrorType.INVALID_REQUEST,
            provider="search_service",
            message=f"Unknown search provider: {provider_name}.",
        )
    selected_providers.append(provider)
```

- [ ] **Step 8: Run search-focused verification**

Run:

```bash
uv run pytest tests/unit/test_app.py tests/unit/providers/search/test_exa.py tests/unit/services/test_search_service.py -v
uv run ruff check src/app.py src/providers/search/exa.py src/services/search_service.py tests/unit/test_app.py tests/unit/providers/search/test_exa.py tests/unit/services/test_search_service.py
```

Expected: all selected tests and ruff pass.

- [ ] **Step 9: Commit**

```bash
git add src/app.py src/providers/search/exa.py src/services/search_service.py tests/unit/test_app.py tests/unit/providers/search/test_exa.py tests/unit/services/test_search_service.py
git commit --author="Codex <codex@agenteum.com>" -m "fix: harden search fallback wiring"
```

---

### Task 3: MCP Tool Schema Constraints

**Files:**
- Modify: `src/api/mcp_full.py`
- Test: `tests/unit/api/test_mcp_full.py`

- [ ] **Step 1: Write failing schema visibility tests**

Add helper and test to `tests/unit/api/test_mcp_full.py`:

```python
def _fake_mcp():
    class FakeSearchService:
        async def search(self, request):
            return SearchResponse(
                query=request.query,
                results=[],
                source="duckduckgo",
                fallbacks=[],
            )

        async def parallel_search(self, request, provider_names=None):
            return ParallelSearchResponse(
                query=request.query,
                results=[],
                sources=provider_names or ["duckduckgo"],
                errors=[],
            )

    class FakeFetchService:
        async def fetch(self, urls):
            return FetchResponse(results=[])

    return create_mcp_server(
        search_service=FakeSearchService(),
        fetch_service=FakeFetchService(),
    )


def test_mcp_tool_schemas_expose_request_constraints():
    mcp = _fake_mcp()

    search_schema = mcp._tool_manager._tools["search"].parameters
    max_result = search_schema["properties"]["max_result"]
    assert max_result["minimum"] == 1
    assert max_result["maximum"] == 20
    assert set(search_schema["properties"]["time_range"]["anyOf"][0]["enum"]) == {
        "day",
        "week",
        "month",
        "year",
        "d",
        "w",
        "m",
        "y",
    }

    parallel_schema = mcp._tool_manager._tools["parallel_search"].parameters
    provider_items = parallel_schema["properties"]["providers"]["anyOf"][0]["items"]
    assert set(provider_items["enum"]) == {"tavily", "exa", "duckduckgo"}

    fetch_schema = mcp._tool_manager._tools["fetch"].parameters
    urls = fetch_schema["properties"]["urls"]
    assert urls["minItems"] == 1
    assert urls["maxItems"] == 10
```

Keep these assertions on `tool.parameters`, because that is where the current FastMCP `Tool` object exposes generated input schema.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/api/test_mcp_full.py::test_mcp_tool_schemas_expose_request_constraints -v
```

Expected: fail because current tool signatures are plain `str`, `int`, and `list[str]`.

- [ ] **Step 3: Move constraints into tool signatures**

Modify imports in `src/api/mcp_full.py`:

```python
from typing import Annotated, Any

from pydantic import Field

from src.schemas import FetchRequest, SearchProviderName, SearchRequest, TimeRange
```

Add aliases near the top:

```python
SearchLimit = Annotated[int, Field(ge=1, le=20)]
FetchUrls = Annotated[list[str], Field(min_length=1, max_length=10)]
ParallelProviders = Annotated[list[SearchProviderName], Field(min_length=1, max_length=3)]
```

Update tool signatures:

```python
async def search(
    query: str,
    max_result: SearchLimit = 10,
    time_range: TimeRange | None = None,
    topic: str | None = None,
) -> dict:
```

```python
async def parallel_search(
    query: str,
    max_result: SearchLimit = 10,
    time_range: TimeRange | None = None,
    topic: str | None = None,
    providers: ParallelProviders | None = None,
) -> dict:
```

```python
async def fetch(urls: FetchUrls) -> dict:
```

Keep constructing `SearchRequest` and `FetchRequest` inside the functions; the schema constraints are for client visibility and early validation.

- [ ] **Step 4: Run MCP API verification**

Run:

```bash
uv run pytest tests/unit/api/test_mcp_full.py -v
uv run ruff check src/api/mcp_full.py tests/unit/api/test_mcp_full.py
```

Expected: all selected tests and ruff pass.

- [ ] **Step 5: Commit**

```bash
git add src/api/mcp_full.py tests/unit/api/test_mcp_full.py
git commit --author="Codex <codex@agenteum.com>" -m "fix: expose mcp tool constraints"
```

---

### Task 4: E2E Test Hygiene

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/e2e/test_opencode_mcp.py`
- Test: add `tests/unit/test_pytest_config.py`

- [ ] **Step 1: Write failing pytest config guard**

Create `tests/unit/test_pytest_config.py`:

```python
from pathlib import Path
import tomllib


def test_pytest_default_excludes_e2e_tests():
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    pytest_config = config["tool"]["pytest"]["ini_options"]

    assert pytest_config["addopts"] == "-m 'not e2e'"
    assert any(marker.startswith("e2e:") for marker in pytest_config["markers"])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/test_pytest_config.py -v
```

Expected: fail because `addopts` and marker registration are not present.

- [ ] **Step 3: Exclude e2e tests by default**

Modify `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
addopts = "-m 'not e2e'"
markers = [
  "e2e: tests that start real local processes or call external agent clients",
]
```

- [ ] **Step 4: Mark the e2e module and remove process killing**

Modify `tests/e2e/test_opencode_mcp.py`:

```python
pytestmark = pytest.mark.e2e
```

Delete `_ensure_port_free()` and its `sys` and platform-specific process-killing imports. Keep `os` only if the final file still uses it; otherwise remove it too.

- [ ] **Step 5: Use a free port and real readiness polling**

Add a TCP readiness helper:

```python
def _wait_for_server(
    proc: subprocess.Popen,
    port: int,
    timeout: float = SERVER_START_TIMEOUT,
) -> None:
    """Wait until the server accepts TCP connections."""
    import socket

    start = time.time()
    while time.time() - start < timeout:
        if proc.poll() is not None:
            raise RuntimeError(f"Server exited early (code={proc.returncode}).")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Server did not accept connections on port {port} within {timeout}s.")
```

Add a handle object and an inline OpenCode config helper:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ServerHandle:
    proc: subprocess.Popen
    port: int
    opencode_env: dict[str, str]


def _opencode_config_content(port: int) -> str:
    return json.dumps(
        {
            "mcp": {
                "agenteum-net": {
                    "type": "remote",
                    "url": f"http://127.0.0.1:{port}/mcp/full",
                    "enabled": True,
                    "oauth": False,
                }
            }
        }
    )
```

Change `_run_opencode()` to accept this environment:

```python
def _run_opencode(
    cmd_args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = OPENCODE_TIMEOUT,
) -> tuple[str, str, int]:
    """Run an opencode sub-command and return (stdout, stderr, returncode)."""
    full_cmd = [_find_opencode(), "--pure"] + cmd_args
    result = subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
        env={**dict(subprocess.os.environ), **(env or {})},
    )
    return result.stdout, result.stderr, result.returncode
```

Change the fixture to use `_free_port()` and return `ServerHandle`:

```python
@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> ServerHandle:
    uv = _find_uv()
    port = _free_port()
    log_dir = tmp_path_factory.mktemp("agenteum-net-e2e")
    stdout_file = (log_dir / "server.stdout.log").open("w", encoding="utf-8")
    stderr_file = (log_dir / "server.stderr.log").open("w", encoding="utf-8")
    env = {
        **dict(subprocess.os.environ),
        "AGENTEUM_HOST": "127.0.0.1",
        "AGENTEUM_PORT": str(port),
        "AGENTEUM_ALLOW_REMOTE": "false",
    }
    opencode_env = {"OPENCODE_CONFIG_CONTENT": _opencode_config_content(port)}
    proc = subprocess.Popen(
        [uv, "run", "agenteum-net"],
        stdout=stdout_file,
        stderr=stderr_file,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    try:
        _wait_for_server(proc, port, timeout=SERVER_START_TIMEOUT)
        yield ServerHandle(proc=proc, port=port, opencode_env=opencode_env)
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        stdout_file.close()
        stderr_file.close()
```

Update e2e tests to pass the inline config to OpenCode:

```python
stdout, stderr, rc = _run_opencode(["mcp", "list"], env=server.opencode_env)
```

Use the same `env=server.opencode_env` argument in the two `opencode run` calls.

- [ ] **Step 6: Run e2e hygiene verification**

Run:

```bash
uv run pytest tests/unit/test_pytest_config.py -v
uv run pytest --collect-only -q
uv run pytest tests/e2e/test_opencode_mcp.py -m e2e --collect-only -q
uv run ruff check tests/e2e/test_opencode_mcp.py tests/unit/test_pytest_config.py
```

Expected: the unit guard passes; default collection deselects e2e tests; explicit e2e collection still sees the opencode tests; ruff passes.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml tests/e2e/test_opencode_mcp.py tests/unit/test_pytest_config.py
git commit --author="Codex <codex@agenteum.com>" -m "test: isolate e2e opencode tests"
```

---

### Task 5: App Lifespan, Timestamped Logging, And Search Eval Validation

**Files:**
- Modify: `src/app.py`
- Modify: `src/evaluation/search_eval.py`
- Test: `tests/unit/test_app.py`
- Test: `tests/unit/evaluation/test_search_eval.py`

- [ ] **Step 1: Write failing lifespan and logging tests**

Add to `tests/unit/test_app.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_create_app_closes_owned_http_clients(monkeypatch):
    clients = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.closed = False
            clients.append(self)

        async def aclose(self):
            self.closed = True

    monkeypatch.setattr("src.app.httpx.AsyncClient", FakeAsyncClient)

    app = create_app(Settings())

    async with app.router.lifespan_context(app):
        pass

    assert len(clients) == 3
    assert all(client.closed for client in clients)


def test_configure_logging_includes_timestamp(monkeypatch):
    captured = {}

    def fake_basic_config(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    configure_logging(Settings(AGENTEUM_LOG_LEVEL="debug"))

    assert captured["level"] == logging.DEBUG
    assert "%(asctime)s" in captured["format"]
```

Update the existing logging test rather than duplicating it if that keeps the file clearer.

- [ ] **Step 2: Write failing search-eval provider validation test**

Add to `tests/unit/evaluation/test_search_eval.py`:

```python
import pytest

from src.evaluation.search_eval import _parse_providers


def test_parse_providers_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        _parse_providers("tavily,unknown")
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_app.py tests/unit/evaluation/test_search_eval.py -v
```

Expected: fail because clients are not closed, logging has no timestamp format, and provider parsing accepts unknown names.

- [ ] **Step 4: Close app-owned clients during lifespan shutdown**

Modify `src/app.py` lifespan:

```python
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
    finally:
        await search_client.aclose()
        await fetch_client.aclose()
        await jina_client.aclose()
```

- [ ] **Step 5: Add timestamped logging format**

Modify `configure_logging()`:

```python
def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
```

- [ ] **Step 6: Validate search-eval provider names early**

Modify `src/evaluation/search_eval.py`:

```python
VALID_PROVIDERS = set(DEFAULT_PROVIDERS)
```

Update `_parse_providers()`:

```python
def _parse_providers(value: str) -> list[str]:
    providers = [provider.strip() for provider in value.split(",") if provider.strip()]
    selected = providers or DEFAULT_PROVIDERS
    unknown = [provider for provider in selected if provider not in VALID_PROVIDERS]
    if unknown:
        raise ValueError(f"Unknown provider: {', '.join(unknown)}")
    return selected
```

Update `main()` so CLI users get a friendly argparse error:

```python
try:
    providers = _parse_providers(args.providers)
except ValueError as exc:
    parser.error(str(exc))
```

- [ ] **Step 7: Run operational verification**

Run:

```bash
uv run pytest tests/unit/test_app.py tests/unit/evaluation/test_search_eval.py -v
uv run ruff check src/app.py src/evaluation/search_eval.py tests/unit/test_app.py tests/unit/evaluation/test_search_eval.py
```

Expected: all selected tests and ruff pass.

- [ ] **Step 8: Commit**

```bash
git add src/app.py src/evaluation/search_eval.py tests/unit/test_app.py tests/unit/evaluation/test_search_eval.py
git commit --author="Codex <codex@agenteum.com>" -m "fix: clean app lifecycle and eval validation"
```

---

## Final Verification

After all tasks are complete, run:

```bash
uv run pytest
uv run pytest tests/e2e/test_opencode_mcp.py -m e2e --collect-only -q
uv run ruff check .
```

Expected:

- Default `uv run pytest` excludes e2e and passes.
- Explicit e2e collection works without starting opencode or the server.
- Ruff passes.

## Self-Review Checklist

- Each accepted high-confidence finding maps to at least one task.
- Disputed items are listed in Scope and not implemented here.
- Fetch still returns one result item per requested URL.
- Search still fails loudly for configured-but-invalid credentials such as 401/403.
- DuckDuckGo remains available when no paid provider keys are configured.
- MCP tool schema constraints match `SearchRequest` and `FetchRequest`.
- E2E tests are opt-in and never terminate processes on a hardcoded port.
