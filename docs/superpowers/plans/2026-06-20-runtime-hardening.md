# Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address the next high-value Claude review findings after the first review-fixes batch: fetch resource limits, private-network fetch blocking, provider timeout/error mapping, and provider-facing documentation.

**Architecture:** Keep provider protocol translation in provider classes and policy/configuration in `Settings` plus app wiring. HTTP fetch owns target validation, response streaming, size limits, and Markdown conversion. Search/fetch providers map library and HTTP errors into `ProviderError`. Resource markdown files document actual runtime behavior for MCP clients.

**Tech Stack:** Python 3.11+, uv, httpx, ddgs, FastAPI, Pydantic Settings, pytest, pytest-asyncio, ruff.

---

## References

- Review reports: `docs/review/260611-claude-review-report.md`, `docs/review/260611-claude-review-report-2.md`
- Prior plan: `docs/superpowers/plans/2026-06-11-review-fixes.md`
- Repository rules: `AGENTS.md`, `rules/code-philosophy.md`, `rules/git-commit-standards.md`

## Scope

Implement these accepted follow-up fixes:

- H3/N6: HTTP fetch response size cap, Markdown conversion off the event loop, explicit DuckDuckGo timeout.
- H4: default SSRF/private network protection for HTTP fetch targets and redirects, with an explicit opt-out setting.
- M4: better error mapping for Jina 429 and DuckDuckGo timeout/rate-limit exceptions.
- Documentation: update `search-guide.md` and `providers-capabilities.md` so they match conditional Tavily/Exa wiring and optional API keys.

Do not implement these in this plan:

- Package rename from `src` to `agenteum_net`.
- Linux/systemd and Windows service hardening.
- Locale/region configuration.
- Full search/fetch chain total-budget enforcement beyond explicit DuckDuckGo timeout and HTTP fetch hardening.
- Jina Reader URL encoding changes.
- `safe_repr()` logging history and fallback-history attachment.

## File Map

- `src/config.py`: add settings for fetch size cap, private fetch allowance, and DuckDuckGo timeout.
- `.env.example`: document new environment variables with conservative defaults.
- `src/app.py`: pass new settings into `HttpFetchProvider` and `DuckDuckGoSearchProvider`.
- `src/providers/fetch/http.py`: validate target IPs, stream response with a size limit, preserve redirects only when every hop is allowed, and convert Markdown in a thread.
- `src/providers/search/duckduckgo.py`: add explicit timeout and map ddgs timeout/rate-limit exceptions.
- `src/providers/fetch/jina.py`: map HTTP 429 to `RATE_LIMITED`.
- `src/resources/search-guide.md`: describe active provider order as conditional on configured keys.
- `src/resources/providers-capabilities.md`: clarify optional API keys and DuckDuckGo-only behavior.
- Tests under `tests/unit/providers/fetch/`, `tests/unit/providers/search/`, `tests/unit/test_config.py`, `tests/unit/test_app.py`, and `tests/unit/api/` as needed.

---

### Task 1: Fetch Private Network Guard And Size Limit

**Files:**
- Modify: `src/config.py`
- Modify: `.env.example`
- Modify: `src/app.py`
- Modify: `src/providers/fetch/http.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_app.py`
- Test: `tests/unit/providers/fetch/test_http_fetch.py`

- [ ] **Step 1: Write failing config tests**

Add to `tests/unit/test_config.py`:

```python
def test_fetch_hardening_defaults_are_conservative():
    settings = Settings()

    assert settings.fetch_max_bytes == 3_000_000
    assert settings.allow_private_fetch is False


def test_fetch_hardening_settings_can_be_configured():
    settings = Settings(
        AGENTEUM_FETCH_MAX_BYTES=1024,
        AGENTEUM_ALLOW_PRIVATE_FETCH=True,
    )

    assert settings.fetch_max_bytes == 1024
    assert settings.allow_private_fetch is True
```

- [ ] **Step 2: Write failing app wiring test**

In `tests/unit/test_app.py`, add a test that monkeypatches `HttpFetchProvider` and captures constructor arguments:

```python
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
```

- [ ] **Step 3: Write failing HTTP provider tests**

Add to `tests/unit/providers/fetch/test_http_fetch.py`:

```python
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
    provider = HttpFetchProvider(
        client=client,
        converter=FakeMarkdownConverter(),
        allow_private_fetch=True,
    )

    result = await provider.fetch("http://127.0.0.1/")

    assert result.status == "ok"
    await client.aclose()


@pytest.mark.asyncio
async def test_http_fetch_rejects_private_redirect_target():
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})
        return httpx.Response(200)

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
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_config.py tests/unit/test_app.py tests/unit/providers/fetch/test_http_fetch.py -v
```

Expected: fail because the new settings, constructor args, private-target checks, redirect checks, and max byte checks are missing.

- [ ] **Step 5: Add settings and app wiring**

Modify `src/config.py`:

```python
fetch_max_bytes: int = Field(default=3_000_000, alias="AGENTEUM_FETCH_MAX_BYTES")
allow_private_fetch: bool = Field(default=False, alias="AGENTEUM_ALLOW_PRIVATE_FETCH")
```

Add a validator:

```python
@field_validator("fetch_max_bytes")
@classmethod
def validate_fetch_max_bytes(cls, value: int) -> int:
    if value < 1:
        raise ValueError("AGENTEUM_FETCH_MAX_BYTES must be at least 1")
    return value
```

Modify the `HttpFetchProvider` construction in `src/app.py`:

```python
HttpFetchProvider(
    client=fetch_client,
    converter=MarkdownConverter(),
    max_bytes=settings.fetch_max_bytes,
    allow_private_fetch=settings.allow_private_fetch,
)
```

Update `.env.example`:

```env
AGENTEUM_FETCH_MAX_BYTES=3000000
AGENTEUM_ALLOW_PRIVATE_FETCH=false
```

- [ ] **Step 6: Implement guarded fetch target validation**

In `src/providers/fetch/http.py`:

- Add constructor parameters `max_bytes: int = 3_000_000`, `allow_private_fetch: bool = False`, `max_redirects: int = 10`.
- Validate the original URL before the first request.
- Disable reliance on client-level automatic redirects for provider logic. The app client may still have `follow_redirects=True`, but provider code should use request-level `follow_redirects=False` and follow redirects manually.
- For every redirect `Location`, resolve relative redirects with `response.url.join(location)`, validate the new target, and continue.
- Reject loopback, private, link-local, multicast, unspecified, and reserved IPs unless `allow_private_fetch=True`.
- For hostnames, use `ipaddress.ip_address()` when the host is already an IP literal. Do not add live DNS resolution in this task; hostname DNS rebinding protection is a separate hardening step.

A minimal helper shape:

```python
def _validate_fetch_target(self, url: str) -> None:
    if self.allow_private_fetch:
        return
    parsed = httpx.URL(url)
    host = parsed.host
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
```

Use `ErrorType.INVALID_REQUEST` for rejected targets.

- [ ] **Step 7: Implement response streaming and thread conversion**

In `src/providers/fetch/http.py`:

- Replace the current eager client request plus `response.text` flow with an internal request method that streams bytes, counts them, and raises if the cap is exceeded.
- Keep content-type and status handling based on headers/status before Markdown conversion.
- Decode bytes using `response.encoding` or httpx response helpers. A practical implementation can build `content = bytes(chunks)` and then set/use a response copy, as long as size is capped first.
- Run Markdown conversion off the event loop:

```python
markdown = await asyncio.to_thread(self.converter.html_to_markdown, html, final_url)
```

Use `ErrorType.UNSUPPORTED_CONTENT` for size cap violations with a clear message such as `"HTTP fetch exceeded maximum response size."`.

- [ ] **Step 8: Run focused verification**

Run:

```bash
uv run pytest tests/unit/test_config.py tests/unit/test_app.py tests/unit/providers/fetch/test_http_fetch.py -v
uv run ruff check src/config.py src/app.py src/providers/fetch/http.py tests/unit/test_config.py tests/unit/test_app.py tests/unit/providers/fetch/test_http_fetch.py
```

Expected: all selected tests and ruff pass.

- [ ] **Step 9: Commit**

```bash
git add .env.example src/config.py src/app.py src/providers/fetch/http.py tests/unit/test_config.py tests/unit/test_app.py tests/unit/providers/fetch/test_http_fetch.py
git commit --author="Codex <codex@agenteum.com>" -m "fix: harden http fetch targets and size"
```

---

### Task 2: DuckDuckGo Timeout And Error Mapping

**Files:**
- Modify: `src/config.py`
- Modify: `.env.example`
- Modify: `src/app.py`
- Modify: `src/providers/search/duckduckgo.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_app.py`
- Test: `tests/unit/providers/search/test_duckduckgo.py`

- [ ] **Step 1: Write failing config and wiring tests**

Add to `tests/unit/test_config.py`:

```python
def test_duckduckgo_timeout_default_and_override():
    assert Settings().duckduckgo_timeout == 15.0
    assert Settings(AGENTEUM_DUCKDUCKGO_TIMEOUT=3.5).duckduckgo_timeout == 3.5
```

Add to `tests/unit/test_app.py`:

```python
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
```

- [ ] **Step 2: Write failing DuckDuckGo provider tests**

Add imports to `tests/unit/providers/search/test_duckduckgo.py`:

```python
from ddgs.exceptions import RatelimitException, TimeoutException

from src.errors import ErrorType, ProviderError
```

Add tests:

```python
class SlowDDGS:
    def text(self, *args, **kwargs):
        import time
        time.sleep(0.2)
        return []


class RateLimitedDDGS:
    def text(self, *args, **kwargs):
        raise RatelimitException("rate limited")


class TimedOutDDGS:
    def text(self, *args, **kwargs):
        raise TimeoutException("timed out")


@pytest.mark.asyncio
async def test_duckduckgo_timeout_maps_to_timeout_error():
    provider = DuckDuckGoSearchProvider(ddgs_factory=lambda: SlowDDGS(), timeout=0.01)

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.TIMEOUT


@pytest.mark.asyncio
async def test_duckduckgo_rate_limit_exception_maps_to_rate_limited():
    provider = DuckDuckGoSearchProvider(ddgs_factory=lambda: RateLimitedDDGS())

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.RATE_LIMITED


@pytest.mark.asyncio
async def test_duckduckgo_library_timeout_exception_maps_to_timeout():
    provider = DuckDuckGoSearchProvider(ddgs_factory=lambda: TimedOutDDGS())

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchRequest(query="mcp"))

    assert raised.value.error_type == ErrorType.TIMEOUT
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_config.py tests/unit/test_app.py tests/unit/providers/search/test_duckduckgo.py -v
```

Expected: fail because timeout setting/wiring and exception mapping are missing.

- [ ] **Step 4: Add setting and app wiring**

Modify `src/config.py`:

```python
duckduckgo_timeout: float = Field(default=15.0, alias="AGENTEUM_DUCKDUCKGO_TIMEOUT")
```

Add a positive-value validator if no generic timeout validator exists.

Modify `_build_search_providers(settings, client, logger)` in `src/app.py`:

```python
providers.append(DuckDuckGoSearchProvider(timeout=settings.duckduckgo_timeout))
```

Update `.env.example`:

```env
AGENTEUM_DUCKDUCKGO_TIMEOUT=15.0
```

- [ ] **Step 5: Implement timeout and exception mapping**

Modify `src/providers/search/duckduckgo.py`:

```python
try:
    from ddgs.exceptions import RatelimitException, TimeoutException
except ImportError:  # pragma: no cover - compatibility with older ddgs releases
    RatelimitException = ()
    TimeoutException = ()


class DuckDuckGoSearchProvider:
    def __init__(self, *, ddgs_factory: type[DDGS] = DDGS, timeout: float = 15.0) -> None:
        self.ddgs_factory = ddgs_factory
        self.timeout = timeout

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._search_sync, request),
                timeout=self.timeout,
            )
        except ProviderError:
            raise
        except TimeoutError as exc:
            raise ProviderError(
                error_type=ErrorType.TIMEOUT,
                provider=self.name,
                message="DuckDuckGo search timed out.",
            ) from exc
        except TimeoutException as exc:
            raise ProviderError(
                error_type=ErrorType.TIMEOUT,
                provider=self.name,
                message="DuckDuckGo search timed out.",
            ) from exc
        except RatelimitException as exc:
            raise ProviderError(
                error_type=ErrorType.RATE_LIMITED,
                provider=self.name,
                message="DuckDuckGo search was rate limited.",
            ) from exc
        except Exception as exc:
            raise ProviderError(
                error_type=ErrorType.PROVIDER_ERROR,
                provider=self.name,
                message="DuckDuckGo search failed.",
                payload={"error": str(exc)},
            ) from exc
```

- [ ] **Step 6: Run focused verification**

Run:

```bash
uv run pytest tests/unit/test_config.py tests/unit/test_app.py tests/unit/providers/search/test_duckduckgo.py -v
uv run ruff check src/config.py src/app.py src/providers/search/duckduckgo.py tests/unit/test_config.py tests/unit/test_app.py tests/unit/providers/search/test_duckduckgo.py
```

Expected: all selected tests and ruff pass.

- [ ] **Step 7: Commit**

```bash
git add .env.example src/config.py src/app.py src/providers/search/duckduckgo.py tests/unit/test_config.py tests/unit/test_app.py tests/unit/providers/search/test_duckduckgo.py
git commit --author="Codex <codex@agenteum.com>" -m "fix: bound duckduckgo search failures"
```

---
### Task 3: Jina Rate Limit Error Mapping

**Files:**
- Modify: `src/providers/fetch/jina.py`
- Test: `tests/unit/providers/fetch/test_jina_fetch.py`

- [ ] **Step 1: Write failing Jina 429 test**

Add to `tests/unit/providers/fetch/test_jina_fetch.py`:

```python
@pytest.mark.asyncio
async def test_jina_rate_limit_maps_to_rate_limited():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too many requests")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = JinaFetchProvider(api_key="key", client=client)

    with pytest.raises(ProviderError) as raised:
        await provider.fetch("https://example.com/")

    assert raised.value.error_type == ErrorType.RATE_LIMITED
    assert raised.value.http_status == 429
    await client.aclose()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/providers/fetch/test_jina_fetch.py::test_jina_rate_limit_maps_to_rate_limited -v
```

Expected: fail because 429 currently maps to `PROVIDER_ERROR`.

- [ ] **Step 3: Implement 429 mapping**

Modify `src/providers/fetch/jina.py` before the non-200 fallback branch:

```python
if response.status_code == 429:
    raise ProviderError(
        error_type=ErrorType.RATE_LIMITED,
        provider=self.name,
        message="Jina returned HTTP 429.",
        http_status=response.status_code,
        payload=response.text,
    )
```

- [ ] **Step 4: Run focused verification**

Run:

```bash
uv run pytest tests/unit/providers/fetch/test_jina_fetch.py -v
uv run ruff check src/providers/fetch/jina.py tests/unit/providers/fetch/test_jina_fetch.py
```

Expected: all selected tests and ruff pass.

- [ ] **Step 5: Commit**

```bash
git add src/providers/fetch/jina.py tests/unit/providers/fetch/test_jina_fetch.py
git commit --author="Codex <codex@agenteum.com>" -m "fix: map jina rate limits"
```

---

### Task 4: Provider Resource Documentation

**Files:**
- Modify: `src/resources/search-guide.md`
- Modify: `src/resources/providers-capabilities.md`
- Test: `tests/unit/api/test_mcp_full.py`

- [ ] **Step 1: Write failing resource doc assertions**

Add to `tests/unit/api/test_mcp_full.py`:

```python
def test_provider_docs_describe_optional_paid_provider_keys():
    capabilities = load_resource_text("providers-capabilities.md")
    search_guide = load_resource_text("search-guide.md")

    assert "Tavily and Exa are enabled only when their API keys are configured" in capabilities
    assert "DuckDuckGo remains available without an API key" in capabilities
    assert "Active provider order skips unconfigured paid providers" in search_guide
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/api/test_mcp_full.py::test_provider_docs_describe_optional_paid_provider_keys -v
```

Expected: fail because current docs still imply fixed provider order and required env vars.

- [ ] **Step 3: Update search guide**

Modify `src/resources/search-guide.md`:

- Replace “Provider fallback order is Tavily, then Exa, then DuckDuckGo.” with:

```markdown
Active provider order skips unconfigured paid providers. When both paid keys are configured, fallback order is Tavily, then Exa, then DuckDuckGo. With no paid keys, DuckDuckGo remains available without an API key.
```

- Replace parallel results order text with:

```markdown
Results are merged in active provider order. Unconfigured paid providers are skipped; duplicate provider names are ignored after their first occurrence. Duplicate URLs keep the first result.
```

- [ ] **Step 4: Update provider capabilities**

Modify `src/resources/providers-capabilities.md`:

- Change the search provider bullets:

```markdown
- Tavily: enabled only when `TAVILY_API_KEY` is configured; first paid search provider.
- Exa: enabled only when `EXA_API_KEY` is configured; fallback paid search provider.
- DuckDuckGo: no API key, always available free fallback provider through `ddgs`.
```

- Replace “Required environment variables” with:

```markdown
Optional environment variables:

- `TAVILY_API_KEY`: enables Tavily.
- `EXA_API_KEY`: enables Exa.
- `JINA_API_KEY`: enables Jina Reader fallback and x.com/twitter.com direct fetches.

Tavily and Exa are enabled only when their API keys are configured. DuckDuckGo remains available without an API key.
```

- [ ] **Step 5: Run focused verification**

Run:

```bash
uv run pytest tests/unit/api/test_mcp_full.py -v
uv run ruff check tests/unit/api/test_mcp_full.py
```

Expected: all selected tests and ruff pass.

- [ ] **Step 6: Commit**

```bash
git add src/resources/search-guide.md src/resources/providers-capabilities.md tests/unit/api/test_mcp_full.py
git commit --author="Codex <codex@agenteum.com>" -m "docs: clarify active provider behavior"
```

---

## Final Verification

After all tasks complete, run:

```bash
uv run pytest
uv run pytest tests/e2e/test_opencode_mcp.py -m e2e --collect-only -q
uv run ruff check .
```

Expected:

- Default test suite passes.
- E2E tests remain excluded by default and collect explicitly with `-m e2e`.
- Ruff passes.

## Self-Review Checklist

- Fetch rejects private/local IP literal targets and private redirects by default.
- `AGENTEUM_ALLOW_PRIVATE_FETCH=true` restores private fetch behavior for trusted deployments.
- HTTP response bodies are capped before Markdown conversion.
- Markdown conversion no longer blocks the event loop.
- DuckDuckGo has an explicit timeout and maps timeout/rate-limit errors.
- Jina 429 maps to `rate_limited`.
- Provider resource docs describe conditional paid provider activation and DuckDuckGo fallback accurately.
- Out-of-scope items were not implemented in this plan.
