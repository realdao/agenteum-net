# Agenteum Net v1.0 Design

Date: 2026-05-22

## 1. Purpose

Agenteum Net is an HTTP-only MCP server that gives coding agents a unified network access layer. Its first version exposes web search and web fetch tools through one MCP endpoint, so agents with weak or missing built-in web access can use the same provider-backed interface.

The project is designed for local and WSL agent clients. It is not intended to be deployed as a public unauthenticated service.

## 2. v1.0 Scope

### Goals

- Provide one HTTP MCP endpoint: `/mcp/full`.
- Expose two tools:
  - `agenteum_search(query, max_result=10, time_range=None, topic=None)`
  - `agenteum_fetch(urls)`
- Implement search providers:
  - Tavily
  - Exa
  - DuckDuckGo
- Implement fetch providers:
  - HTTP request + HTML to Markdown conversion
  - Jina Reader API
- Load provider keys and runtime settings from `.env` or environment variables.
- Return stable unified schemas from service and MCP layers.
- Use TDD for provider, service, API, and smoke behavior.

### Non-Goals

- No stdio MCP transport in v1.0.
- No `/mcp/lite` or per-client endpoint variants in v1.0.
- No authentication in v1.0.
- No hand-written REST replacement for MCP in v1.0. The HTTP endpoint must speak MCP Streamable HTTP.
- No browser provider in v1.0.
- No Playwright-based fetch strategy.
- No policy DSL or configurable provider strategy engine.
- No search provider parallelism in v1.0.
- No PDF fetch behavior in v1.0, even though MarkItDown is selected partly for future PDF support.
- No real external API calls in the default automated test suite.

## 3. Runtime Configuration

Configuration is read from `.env` or environment variables.

```env
AGENTEUM_HOST=127.0.0.1
AGENTEUM_PORT=8765
AGENTEUM_ALLOW_REMOTE=false
TAVILY_API_KEY=tvly-...
EXA_API_KEY=...
JINA_API_KEY=jina_...
```

The service is intended for trusted local use. The default bind host is `127.0.0.1`. Binding to `0.0.0.0` is allowed only when `AGENTEUM_ALLOW_REMOTE=true`, which is useful for some WSL client setups. When remote binding is enabled, startup must log a `WARNING` that v1.0 has no authentication and must not be exposed to an untrusted network.

Provider order is hard-coded in v1.0:

- Search: Tavily -> Exa -> DuckDuckGo
- Fetch: x.com/twitter.com -> Jina, other URLs -> HTTP -> Jina fallback when content appears blocked or empty

## 4. Project Layout

Implementation code lives directly under `src/`. Tests live beside `src/`.

```text
agenteum-net/
  pyproject.toml
  README.md
  .env.example
  src/
    __init__.py
    app.py
    config.py
    schemas.py
    errors.py
    api/
      __init__.py
      mcp_full.py
      transport.py
    providers/
      __init__.py
      search/
        __init__.py
        base.py
        tavily.py
        exa.py
        duckduckgo.py
      fetch/
        __init__.py
        base.py
        http.py
        jina.py
    services/
      __init__.py
      search_service.py
      fetch_service.py
    resources/
      __init__.py
      tool_guides.py
      search-guide.md
      fetch-guide.md
      providers-capabilities.md
    utils/
      __init__.py
      content_detection.py
      headers.py
      markdown.py
      urls.py
      logging.py
  tests/
    unit/
      providers/
      services/
      api/
    smoke/
```

## 5. Module Boundaries

### Providers

Providers wrap one external capability. They are responsible for:

- Building provider-specific requests.
- Calling external APIs or HTTP endpoints.
- Mapping successful responses into unified schema objects.
- Translating provider-specific failures into internal errors.

Providers must not implement fallback policy.

### Services

Services implement product behavior:

- `SearchService` applies the Tavily -> Exa -> DuckDuckGo fallback chain.
- `FetchService` applies URL routing, HTTP-first fetch behavior, Jina fallback, and partial failure handling.

Services depend on provider interfaces, not concrete HTTP details.

### API

The API layer registers MCP tools and resources. It should not contain provider-specific logic.

`api/transport.py` isolates the MCP SDK mounting details. In v1.0 it creates and mounts the official SDK Streamable HTTP app. It exists to keep SDK transport churn out of `api/mcp_full.py`; it is not a commitment to support stdio in v1.0.

### Schemas

`schemas.py` defines Pydantic models for tool inputs, service outputs, result items, fallback records, and structured errors.

### Errors

`errors.py` defines internal error types and a provider exception class. Service code should branch on internal error types instead of provider-specific response formats.

Provider errors must have a safe representation for logs. Raw provider payloads may be retained for debugging, but default logging must redact common secret fields such as `api_key`, `authorization`, `token`, and `secret`, and truncate payload text to a bounded length such as 500 characters.

## 6. Search Contract

### Tool Input

```json
{
  "query": "string",
  "max_result": 10,
  "time_range": null,
  "topic": null
}
```

Rules:

- `query` is required.
- `max_result` defaults to 10.
- `max_result` is capped at 20 at the schema/service boundary.
- Each provider is responsible for adapting or truncating `max_result` to its own supported limit before making the external request.
- `time_range` is best-effort. Supported values are `day`, `week`, `month`, `year`, `d`, `w`, `m`, and `y` where the provider supports them.
- `topic` is best-effort. Tavily supports `general`, `news`, and `finance`; other providers may ignore unsupported topic values.
- Each provider should keep local mapping tables such as `_TIME_RANGE_MAP` and `_TOPIC_MAP`. Unsupported values are filtered or ignored instead of being sent blindly.

### Tool Output

```json
{
  "query": "string",
  "results": [
    {
      "title": "string",
      "url": "string",
      "snippet": "string | null",
      "published_at": "string | null",
      "source": "tavily | exa | duckduckgo",
      "score": "float | null"
    }
  ],
  "source": "tavily | exa | duckduckgo",
  "fallbacks": [
    {
      "from": "tavily",
      "to": "exa",
      "reason": "quota_exhausted"
    }
  ]
}
```

`source` is the provider that produced the returned result list. `fallbacks` records provider changes for observability.

## 7. Search Providers

### Tavily

The Tavily provider should call the REST API with `httpx`, not the official SDK, so tests can inject a mock transport and simulate exact HTTP responses.

Tavily parameter mapping:

- `time_range`: map canonical values to Tavily-supported values. `day`/`d`, `week`/`w`, `month`/`m`, and `year`/`y` are accepted.
- `topic`: pass through only `general`, `news`, and `finance`.
- `max_result`: pass as `max_results`, capped at 20.

Expected mapping:

- `results[].title` -> `title`
- `results[].url` -> `url`
- `results[].content` -> `snippet`
- `results[].score` -> `score`
- `published_at` is null unless Tavily response includes a usable published date field
- `source` is `tavily`

Error mapping:

- HTTP 400 -> `invalid_request`
- HTTP 401 or 403 -> `auth_error`
- HTTP 429 -> `rate_limited`
- HTTP 432 or 433 -> `quota_exhausted`
- HTTP 500+ -> `provider_5xx`
- Timeout -> `timeout`
- Connect/network failure -> `network`
- Malformed JSON or missing required response shape -> `invalid_response`

### Exa

The Exa provider should call the REST API with `httpx`, not the official SDK, so tests can inject a mock transport.

Exa parameter mapping:

- `time_range`: map canonical values to Exa-supported filters if the selected Exa endpoint supports them. Unsupported values are ignored.
- `topic`: ignored in v1.0 unless the selected Exa endpoint exposes a compatible parameter.
- `max_result`: pass using Exa's result count parameter after provider-local limit enforcement.

Expected mapping:

- provider title field -> `title`
- provider URL field -> `url`
- provider text/highlight/summary field -> `snippet`
- provider published date field, if present -> `published_at`
- provider score field, if present -> `score`
- `source` is `exa`

Error mapping:

- HTTP 400 or Exa validation tags such as `INVALID_REQUEST_BODY` -> `invalid_request`
- HTTP 401 or tag `INVALID_API_KEY` -> `auth_error`
- HTTP 402 with `NO_MORE_CREDITS`, `API_KEY_BUDGET_EXCEEDED`, or `TEAM_BUDGET_EXCEEDED` -> `quota_exhausted`
- HTTP 403 with access or feature tags -> `auth_error`
- HTTP 429 -> `rate_limited`
- HTTP 500, 502, or 503 -> `provider_5xx`
- Timeout -> `timeout`
- Connect/network failure -> `network`
- Malformed JSON or missing required response shape -> `invalid_response`

### DuckDuckGo

DuckDuckGo is the free fallback provider. It does not require an API key. v1.0 should use a small wrapper around the current `ddgs` package API, rather than parsing DuckDuckGo HTML directly. The wrapper keeps dependency details out of the service and makes tests easy to fake.

It should map results to the same `SearchResult` schema and set `source` to `duckduckgo`.

DuckDuckGo parameter mapping:

- `time_range`: pass only values supported by `ddgs`; ignore unsupported values.
- `topic`: ignored in v1.0.
- `max_result`: apply provider-local limit enforcement and truncate returned results if needed.

DuckDuckGo errors are mapped into the same internal error set, but there is no later search provider to fallback to in v1.0.

## 8. Search Service Strategy

The v1.0 search fallback chain is fixed:

```text
Tavily -> Exa -> DuckDuckGo
```

Fallback behavior:

- `quota_exhausted`: fallback.
- `rate_limited`: fallback.
- `timeout`: fallback.
- `network`: fallback.
- `provider_5xx`: fallback.
- `auth_error`: do not fallback.
- `config_error`: do not fallback.
- `invalid_request`: do not fallback.
- `invalid_response`: fallback immediately and log the malformed provider response through the safe error representation. v1.0 does not add retry or exponential backoff for this error type.

If all fallback-capable providers fail, the service raises or returns a structured top-level provider error according to the MCP tool error handling chosen during implementation planning.

Search v1.0 does not merge results from multiple providers. The first successful provider returns the full result set.

## 9. Fetch Contract

### Tool Input

```json
{
  "urls": ["https://example.com"]
}
```

Rules:

- `urls` is required.
- `urls` must contain at least one URL.
- `urls` is capped at 10 items in v1.0 and should be validated in the schema layer.
- Each URL must be HTTP or HTTPS.
- There is no `format` parameter in v1.0.

### Tool Output

```json
{
  "results": [
    {
      "url": "https://example.com",
      "final_url": "https://example.com",
      "content": "# markdown content",
      "source": "http | jina",
      "status": "ok | error",
      "error": null
    }
  ]
}
```

Failed item example:

```json
{
  "url": "https://blocked.example",
  "final_url": null,
  "content": null,
  "source": "http",
  "status": "error",
  "error": {
    "type": "blocked",
    "message": "Content appears to be blocked by an anti-bot page.",
    "provider": "http"
  }
}
```

Batch fetch allows partial failure. One failed URL must not fail the entire tool call.

`final_url` means the final URL where content was actually read after redirects. For the HTTP provider this is `httpx`'s final response URL after following redirects. For Jina, `final_url` is the provider-reported final URL when available; otherwise it is the original input URL.

## 10. Fetch Providers

### HTTP Provider

The HTTP provider uses `httpx` and the following fixed headers:

```text
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8
Accept-Language: zh-CN,zh;q=0.9,en;q=0.8
```

It only supports HTML in v1.0.

Markdown conversion:

- Use Microsoft MarkItDown for HTML to Markdown conversion.
- The HTTP provider controls fetching. MarkItDown must receive already fetched content through a narrow conversion API such as `convert_stream()` or `convert_response()` instead of fetching URLs itself, so headers, timeout, logging, and fallback decisions stay under our control.
- `format=text` is not supported in v1.0.

HTTP provider error mapping:

- Non-HTML or binary content such as PDF/image/zip -> `unsupported_content`
- Empty response body -> `empty_content`
- Empty or extremely short converted Markdown -> `empty_content`
- Common anti-bot/challenge text -> `blocked`
- HTTP 4xx where content cannot be used -> `provider_error` or a more specific internal error when clear
- HTTP 5xx -> `provider_5xx`
- Timeout -> `timeout`
- Connect/network failure -> `network`
- MarkItDown conversion failure -> `invalid_response`

Blocked-content detection:

- Implement the heuristic in `utils/content_detection.py`.
- The detector should inspect the response title, raw HTML text, and converted Markdown.
- Initial case-insensitive markers include:
  - `access denied`
  - `captcha`
  - `cloudflare`
  - `checking your browser`
  - `enable javascript`
  - `verify you are human`
  - `unusual traffic`
  - `bot detection`
  - `forbidden`
  - `temporarily blocked`
- The heuristic is intentionally conservative. It is allowed to miss some blocked pages, but it should avoid classifying ordinary pages as blocked based on a single weak marker.

### Jina Provider

The Jina provider calls Jina Reader API and treats the response as Markdown content.

Rules:

- Use `JINA_API_KEY` from `.env`.
- Return Markdown content directly.
- Set `source` to `jina`.
- Set `final_url` to the Jina-reported resolved URL when available, otherwise the input URL.
- If Jina fails for one URL, that URL result is marked `status=error`; other URLs continue.

## 11. Fetch Service Strategy

Routing:

```text
x.com / twitter.com -> Jina
other URLs -> HTTP
```

Fallback:

- HTTP `blocked` -> fallback to Jina.
- HTTP `empty_content` -> fallback to Jina.
- HTTP `timeout`, `network`, or `provider_5xx` -> fallback to Jina.
- HTTP `invalid_response` -> fallback to Jina.
- HTTP `unsupported_content` -> no fallback in v1.0, except forced Jina routes such as x.com/twitter.com.
- HTTP `invalid_request`, `config_error`, and clearly invalid URLs -> no fallback.

The service returns one `FetchResult` per requested URL. It must preserve input order.

## 12. Internal Error Types

The internal error enum includes:

```text
quota_exhausted
rate_limited
auth_error
config_error
invalid_request
invalid_response
timeout
network
provider_5xx
blocked
empty_content
unsupported_content
provider_error
```

`provider_error` is the fallback bucket for provider failures that do not fit a more specific type. For example, HTTP 500 maps to `provider_5xx`; an unexpected non-standard provider status can map to `provider_error`.

Provider exceptions carry:

- error type
- provider name
- human-readable message
- optional HTTP status code
- optional provider request ID
- optional original response payload for safe logs, not for default MCP output
- a `safe_repr()` or equivalent method that redacts secrets and truncates payload data before logging

## 13. MCP API Design

v1.0 exposes one HTTP MCP endpoint:

```text
/mcp/full
```

Implementation should use the official MCP Python SDK with Streamable HTTP. It should not implement a custom REST-shaped approximation of MCP.

Preferred mounting shape:

```python
mcp = FastMCP(
    "Agenteum Net",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)

app.mount("/mcp/full", mcp.streamable_http_app())
```

If FastAPI mounting requires Starlette lifespan wiring for the SDK session manager, that wiring belongs in `api/transport.py`. The public endpoint remains `/mcp/full`.

Tools:

```text
agenteum_search(query, max_result=10, time_range=None, topic=None)
agenteum_fetch(urls)
```

Tool descriptions should tell agents:

- Use search to discover relevant URLs and summaries.
- Use fetch to read known URLs as Markdown.
- Search `time_range` and `topic` are best-effort.
- Fetch is Markdown-only.
- Fetch supports multiple URLs and partial failure.
- x.com/twitter.com fetches route directly to Jina.

## 14. MCP Resources

v1.0 resources:

```text
agenteum://tools/search-guide
agenteum://tools/fetch-guide
agenteum://providers/capabilities
```

Resource content:

- `search-guide`: tool purpose, parameters, fallback chain, result interpretation.
- `fetch-guide`: batch behavior, Markdown-only output, partial failure semantics, Jina fallback behavior.
- `providers/capabilities`: provider list, required env vars, capability boundaries, common error types.

Resources are documentation for MCP clients and agents. They are not required for tool execution.

Resource body text should live in Markdown files under `src/resources/` and be loaded by `tool_guides.py` at startup. This keeps the guide content easy to edit without touching Python string literals.

## 15. Logging And Observability

v1.0 should use structured logging fields where practical. JSON logging is not required for the first implementation, but logs must carry consistent fields through `extra=` or an equivalent mechanism.

Provider call logs should include:

- `provider`
- `operation`
- `latency_ms`
- `status`
- `error_type` when failed
- `http_status` when available

Fallback logs should include:

- `operation`
- `from_provider`
- `to_provider`
- `reason`
- `fallback_count`

Secrets must not appear in logs. Provider errors should be logged through their safe representation.

## 16. TDD Strategy

Automated tests avoid real external API calls by default.

### Provider Tests

Provider tests use `httpx.MockTransport` or equivalent test doubles to simulate HTTP responses and network exceptions.

Search provider tests:

- Tavily success maps to unified schema.
- Tavily 400 maps to `invalid_request`.
- Tavily 401/403 maps to `auth_error`.
- Tavily 429 maps to `rate_limited`.
- Tavily 432/433 maps to `quota_exhausted`.
- Tavily 500 maps to `provider_5xx`.
- Tavily timeout/network/malformed JSON map correctly.
- Exa success maps to unified schema.
- Exa 401 or `INVALID_API_KEY` maps to `auth_error`.
- Exa 402 quota/budget tags map to `quota_exhausted`.
- Exa 429 maps to `rate_limited`.
- Exa 500/502/503 maps to `provider_5xx`.
- DuckDuckGo success maps to unified schema.

Fetch provider tests:

- HTTP provider sends the required headers.
- HTML response converts to Markdown through MarkItDown.
- MarkItDown integration is tested with fixed HTML input and expected Markdown output. When isolation is needed, inject a fake converter object instead of mocking MarkItDown internals.
- PDF or other non-HTML content maps to `unsupported_content`.
- Empty body maps to `empty_content`.
- Anti-bot page text maps to `blocked`.
- Jina success returns Markdown.
- Missing Jina key maps to `config_error`.
- The blocked-content detector is tested with both positive examples and ordinary-page negatives.
- The `ddgs` wrapper is tested with a fake `DDGS` object or equivalent wrapper fake, so tests do not issue real DuckDuckGo requests.

### Service Tests

Service tests use fake providers, not HTTP mocks.

Search service tests:

- Tavily success does not call Exa or DuckDuckGo.
- Tavily `quota_exhausted` falls back to Exa.
- Tavily `rate_limited` falls back to Exa.
- Tavily and Exa quota failures fall back to DuckDuckGo.
- `auth_error`, `config_error`, and `invalid_request` stop the chain.
- Fallback records preserve provider names and reasons.

Fetch service tests:

- x.com and twitter.com route directly to Jina.
- Normal URLs use HTTP first.
- HTTP `blocked` falls back to Jina.
- HTTP `empty_content` falls back to Jina.
- HTTP `unsupported_content` returns an item-level error without Jina fallback.
- Multi-URL fetch preserves input order.
- One URL failure does not fail the whole tool result.

### API and Smoke Tests

API tests:

- MCP tool registration includes `agenteum_search`.
- MCP tool registration includes `agenteum_fetch`.
- MCP resources include the three guide resources.
- Tool handlers call service methods with validated inputs.

Smoke tests:

- App can be created with test settings.
- `/mcp/full` responds to a basic MCP request through the official MCP client SDK when practical.
- Tool list includes both v1.0 tools.
- Resource list includes v1.0 resources.

## 17. Implementation Notes

- Use `uv` for package management.
- Use Pydantic for schemas and validation.
- Use `httpx` for provider HTTP clients.
- Use Microsoft MarkItDown for HTML to Markdown conversion.
- Use a small `utils/headers.py` helper for the fixed User-Agent and fetch headers. v1.0 does not need a full User-Agent rotation class, but this helper keeps a future rotation strategy from touching the HTTP provider.
- Prefer dependency injection for provider clients and services so tests can use mocks/fakes.
- Keep fallback logic in services, not providers.
- Keep MCP registration thin.
- Do not place provider API keys in code or tests.
- Validate remote binding in `config.py`: `0.0.0.0` or other non-loopback hosts require `AGENTEUM_ALLOW_REMOTE=true`.

## 18. Open Decisions For Implementation Planning

These decisions are intentionally deferred to the implementation plan because they do not change the architecture:

- Exact Python package dependencies and version constraints.
- Exact MCP SDK version and any minor lifespan wiring required by that version.
- Default request timeout values.
- Whether top-level search failure is returned as a structured MCP tool result or raised as an MCP tool error.
