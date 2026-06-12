# Agenteum Net 代码审查报告

> 审查日期: 2026-06-11  
> 审查范围: 完整代码库（src/、tests/、pyproject.toml）  
> 审查维度: 安全性、正确性、性能、可维护性、资源管理

---

## 执行摘要

本次审查共发现 **17 个问题**，其中：

| 严重程度 | 数量 | 说明 |
|---------|------|------|
| 🔴 严重 | 5 | 资源泄漏、数据丢失、服务阻塞，必须立即修复 |
| 🟡 中等 | 6 | 功能缺陷、类型不一致、隐私风险，建议尽快修复 |
| 🟢 轻微 | 6 | 代码异味、设计缺陷、测试不足，按计划修复 |

---

## 🔴 严重问题（必须修复）

### 1. AsyncClient 资源泄漏

**文件**: `src/app.py:28-30`

**问题描述**:  
`create_app()` 中创建了 3 个 `httpx.AsyncClient` 实例，但从未在应用生命周期结束时关闭它们。FastAPI 的 `lifespan` 仅处理了 MCP app 的生命周期上下文，完全忽略了 HTTP client 的清理。

**影响**:  
长时间运行或频繁重启后，TCP 连接池中的连接不会被释放，最终耗尽系统文件描述符，导致新请求失败。在生产环境中可导致服务完全不可用。

**代码**:

```python
search_client = httpx.AsyncClient(timeout=settings.request_timeout)
fetch_client = httpx.AsyncClient(timeout=settings.fetch_timeout, follow_redirects=True)
jina_client = httpx.AsyncClient(timeout=settings.jina_timeout)
```

**修复建议**:  
在 lifespan 的 `yield` 之后添加 client 关闭逻辑：

```python
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_app.router.lifespan_context(mcp_app):
        yield
    await search_client.aclose()
    await fetch_client.aclose()
    await jina_client.aclose()
```

---

### 2. FetchService 中单个 URL 失败导致全部结果丢失

**文件**: `src/services/fetch_service.py:33-35`, `src/services/fetch_service.py:58-64`

**问题描述**:  
`FetchService.fetch()` 使用 `asyncio.gather()` 的默认模式（`return_exceptions=False`）。`_fetch_one()` 在处理需要 Jina 优先的 URL 时，如果 Jina 出现 `CONFIG_ERROR` 或 `AUTH_ERROR`，会直接 raise 异常，导致整个 `gather` 失败。

**失败场景**:  
用户请求 `fetch(["https://example.com", "https://twitter.com/someuser"])`：

1. 第二个 URL 匹配 `is_jina_first_url()` → 直接调用 Jina provider
2. Jina 未配置（`JINA_API_KEY` 缺失）→ `_fetch_with_item_error()` 中检测到 `CONFIG_ERROR` → **直接 raise**
3. `asyncio.gather` 中一个 task 抛异常 → **所有 URL 的结果全部丢失**
4. 第一个 URL（example.com）本可以通过 HTTP fetch 成功获取，但用户收不到任何结果

**修复建议**:  

**方案 A**（推荐）：在 `_fetch_one` 中捕获所有异常，永远返回 `FetchResult`：

```python
async def _fetch_one(self, url: str) -> FetchResult:
    try:
        if is_jina_first_url(url):
            return await self._fetch_with_item_error(self.jina_provider, url)
        # ... existing logic ...
    except ProviderError as exc:
        if exc.error_type in {ErrorType.CONFIG_ERROR, ErrorType.AUTH_ERROR}:
            # 转换为 error result 而非 raise
            return self._error_result(url, "jina", exc)
        raise
```

**方案 B**：使用 `gather(return_exceptions=True)`：

```python
results = await asyncio.gather(
    *(self._fetch_one(url) for url in urls),
    return_exceptions=True
)
# 将异常转换为 FetchResult error
```

---

### 3. Jina reader URL 拼接未编码

**文件**: `src/providers/fetch/jina.py:32`

**问题描述**:  
目标 URL 直接拼接到 Jina Reader 的 base URL 后面，未进行 URL 编码。当目标 URL 包含查询参数、片段标识符或特殊字符时，拼接后的 URL 语义会发生变化。

**失败场景**:  

| 原始 URL | 拼接后 URL | 问题 |
|---------|-----------|------|
| `https://example.com?q=a&b=1` | `https://r.jina.ai/https://example.com?q=a&b=1` | `b=1` 可能被 Jina 解析为自身参数 |
| `https://example.com/path#section` | `https://r.jina.ai/https://example.com/path#section` | `#section` 被解析为 fragment，请求可能不包含路径部分 |
| `https://user:pass@example.com` | `https://r.jina.ai/https://user:pass@example.com` | 认证信息泄露到请求 URL 中 |

**修复建议**:  

```python
from urllib.parse import quote

reader_url = f"{JINA_READER_BASE_URL}/{quote(url, safe='')}"`
```

---

### 4. DuckDuckGo 搜索无超时控制

**文件**: `src/providers/search/duckduckgo.py:30`

**问题描述**:  
`asyncio.to_thread(self._search_sync, request)` 没有超时参数。`ddgs.text()` 是对第三方服务的同步调用，如果 DDGS 服务器无响应或网络异常，调用会无限期阻塞。

**失败场景**:  

1. DDGS 服务不可用时，该协程永不返回
2. `asyncio.to_thread` 占用线程池中的一个线程
3. 多次请求后线程池耗尽
4. 所有 DuckDuckGo 搜索和依赖线程池的其他操作全部卡住
5. 整个服务逐渐失去响应能力

**修复建议**:  

```python
import asyncio

async def search(self, request: SearchRequest) -> list[SearchResult]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(self._search_sync, request),
            timeout=15.0  # 或其他合理值
        )
    except asyncio.TimeoutError:
        raise ProviderError(
            error_type=ErrorType.TIMEOUT,
            provider=self.name,
            message="DuckDuckGo search timed out.",
        )
    # ... existing exception handling ...
```

---

### 5. Provider 内部创建的 AsyncClient 不关闭

**文件**: `src/providers/search/tavily.py:37`, `src/providers/search/exa.py:26`, `src/providers/fetch/http.py:24`

**问题描述**:  
多个 Provider 的 `__init__` 中使用了 `self.client = client or httpx.AsyncClient(timeout=timeout)` 模式。当外部调用者未传入 client 时，内部创建的新 AsyncClient 实例没有提供关闭机制。Provider 类没有实现 `__aenter__/__aexit__` 或 lifespan 管理。

**失败场景**:  

1. 在测试、CLI 工具、独立脚本中反复创建 provider 实例
2. 每个实例泄漏一个 AsyncClient，每个 AsyncClient 维护独立的连接池
3. 系统文件描述符和内存持续增长
4. 最终触发 `OSError: [Errno 24] Too many open files`

**涉及代码**:

```python
# tavily.py
self.client = client or httpx.AsyncClient(timeout=timeout)

# exa.py
self.client = client or httpx.AsyncClient(timeout=timeout)

# http.py
self.client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
```

**修复建议**:  
为 Provider 添加异步上下文管理器支持：

```python
class TavilySearchProvider:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._own_client:  # 标记内部创建的 client
            await self.client.aclose()
```

---

## 🟡 中等问题（建议修复）

### 6. MCP tool 参数类型与 Pydantic 验证不一致

**文件**: `src/api/mcp_full.py:22-26`

**问题描述**:  
MCP tool 签名中 `time_range: str | None = None`，但 `SearchRequest` 的 `time_range` 字段类型是 `TimeRange | None`（`Literal["day", "week", "month", "year", "d", "w", "m", "y"]`）。用户传入无效值时，MCP 层面通过验证，但在 `SearchRequest(...)` 构造时抛出 `ValidationError`。

**影响**:  
异常以内部错误形式传播到 MCP 客户端，用户无法获得清晰的参数错误提示。

**修复建议**:  

```python
from src.schemas import TimeRange

@mcp.tool()
async def search(
    query: str,
    max_result: int = 10,
    time_range: TimeRange | None = None,
    topic: str | None = None,
) -> dict:
    # ...
```

---

### 7. URL 归一化不一致导致计数偏差

**文件**: `src/evaluation/search_eval.py:287-288` vs `src/services/search_service.py:174-175`

**问题描述**:  
`search_eval._normalize_url()` 仅执行 `url.rstrip("/")`，而 `SearchService._normalize_url_for_deduplication()` 还执行了 `urldefrag(url).url.rstrip("/")`（去除 URL fragment）。两者归一化逻辑不一致。

**失败场景**:  

1. Provider 返回结果包含 URL `https://example.com/page#section`
2. 单个 provider run 计数：`search_eval._normalize_url()` → `https://example.com/page#section`
3. Parallel response 结果：`SearchService` 去重后 → `https://example.com/page`
4. 两者被视为不同 URL
5. `parallel_unique_urls` 和 `parallel_added_over_best_provider` 计算出现偏差

**修复建议**:  
复用 `SearchService` 的归一化逻辑，或统一实现到一个共享工具函数中。

---

### 8. Markdown 表格未转义查询字符串

**文件**: `src/evaluation/search_eval.py:134-136`, `src/evaluation/search_eval.py:142`

**问题描述**:  
查询字符串直接插入 Markdown 表格内容，未对 `|`（表格列分隔符）、换行符等特殊字符进行转义。

**失败场景**:  

| 查询输入 | 生成行 | 渲染结果 |
|---------|-------|---------|
| `Python \| JavaScript` | `\| Python \| JavaScript \| 3 \| 1 \| - \|` | 列错位，6 列而非 4 列 |
| `line1\nline2` | 含实际换行 | Markdown 表格断裂 |

**修复建议**:  

```python
def _escape_md_table(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")

lines.append(
    f"| {_escape_md_table(evaluation.query)} | {evaluation.parallel_unique_urls} | "
    f"{evaluation.parallel_added_over_best_provider} | {failed} |"
)
```

---

### 9. SearchService 未处理 CancelledError

**文件**: `src/services/search_service.py:90`

**问题描述**:  
`asyncio.gather(*tasks, return_exceptions=True)` 只捕获 `Exception` 子类的异常，不捕获 `BaseException`（如 `asyncio.CancelledError`、`KeyboardInterrupt`）。当操作被取消时，已完成的 provider 结果被丢弃，部分 provider 可能仍在后台运行。

**失败场景**:  

1. 用户发起 `parallel_search` 请求
2. Tavily 已完成，Exa 仍在运行
3. 客户端断开连接 / 超时取消
4. `CancelledError` 从 gather 传播
5. Tavily 的结果丢失，Exa 的 task 可能未收到取消信号继续运行

**修复建议**:  

```python
async def parallel_search(self, request, provider_names=None):
    selected_providers = self._select_parallel_providers(provider_names)
    tasks = [provider.search(request) for provider in selected_providers]
    try:
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        raise
    # ... rest of method ...
```

---

### 10. 日志可能泄露搜索结果内容

**文件**: `src/api/mcp_full.py:47-54`, `src/api/mcp_full.py:86-92`

**问题描述**:  
`logger.debug()` 将整个搜索结果（包含 URL、标题、摘要等）以 `%s` 格式记入日志。

**影响**:  

- 如果日志级别设置为 DEBUG，用户的完整搜索历史被记录到日志文件
- 日志文件可能被持久化到磁盘、发送到日志聚合服务
- 存在隐私泄露风险（用户搜索了哪些网站、什么内容）
- 搜索结果可能包含长文本，日志量膨胀

**修复建议**:  
只记录结果元数据：

```python
logger.debug(
    "tool result function=%s result_count=%s sources=%s",
    "parallel_search",
    len(response.results),
    response.sources,
    extra={
        "function": "parallel_search",
        "result_count": len(response.results),
        "sources": response.sources,
    },
)
```

---

### 11. `looks_blocked` 子串匹配可能误报

**文件**: `src/utils/content_detection.py:32`

**问题描述**:  
`looks_blocked()` 使用纯子串匹配来判断页面是否被拦截。`STRONG_BLOCKED_MARKERS` 包含 `captcha`、`access denied`、`enable javascript` 等常见字符串。

**失败场景**:  

- 一篇题为 *"How to Build a CAPTCHA System"* 的教程 → 标题含 `captcha` → **误判为被拦截**
- 一篇 *"Access Denied: Understanding HTTP 403"* 的文章 → 标题含 `access denied` → **误判为被拦截**
- 正常网站使用了 Cloudflare CDN（非拦截页面）→ 内容含 `cloudflare` → **误判为被拦截**

**修复建议**:  

- 将检测范围缩小到 `<title>` 标签内
- 增加上下文判断（被拦截页面的 title 通常很短）
- 使用正则表达式匹配完整单词而非子串

---

## 🟢 轻微问题 / 代码异味

### 12. SearchRequest.topic 无值域验证

**文件**: `src/schemas.py:18`

**问题描述**:  `topic: str | None = None` 没有任何值域验证。Tavily provider 只接受 `general`/`news`/`finance`，但无效值被静默忽略而非报错。

**修复建议**:  添加 Pydantic validator 或改用 Literal 类型。

---

### 13. `redact_payload` 不处理自定义对象

**文件**: `src/errors.py:38-50`

**问题描述**:  `redact_payload` 只处理 `dict`/`list`/`tuple`/`str` 类型。其他类型（`set`、`datetime`、自定义对象）直接返回原值，可能包含敏感数据。

**修复建议**:  增加兜底处理：

```python
try:
    return redact_payload(vars(payload))
except TypeError:
    return str(payload)
```

---

### 14. 测试覆盖严重不足

**问题描述**:  整个项目仅有 1 个 smoke test + 4 个 evaluation unit test（共 137 行测试代码）。以下模块完全缺乏测试：

- `FetchService`（fallback 逻辑、错误处理）
- `SearchService`（串行 fallback、parallel dedup、provider 选择）
- `HttpFetchProvider`（content-type 检查、blocked 检测、HTML 转换）
- `JinaFetchProvider`（reader URL 构造、header 处理）
- `TavilySearchProvider`（请求构造、响应解析、错误映射）
- `ExaSearchProvider`（响应解析、quota 检测）
- `DuckDuckGoSearchProvider`（同步调用、结果过滤）
- `content_detection`（各种被拦截页面的检测）
- `config`（环境变量解析、验证器）

**修复建议**:  按优先级添加单元测试和集成测试，先覆盖核心服务层（fetch_service、search_service）。

---

### 15. 始终实例化所有 provider

**文件**: `src/evaluation/search_eval.py:200-205`

**问题描述**:  `--providers tavily` 时仍创建 Exa 和 DuckDuckGo 实例。如果环境缺少 `EXA_API_KEY`，ExaSearchProvider 初始化可能触发不必要的验证或失败。

**修复建议**:  根据 `--providers` 参数动态创建所需 provider：

```python
provider_map = {
    "tavily": lambda: TavilySearchProvider(api_key=settings.tavily_api_key, client=client),
    "exa": lambda: ExaSearchProvider(api_key=settings.exa_api_key, client=client),
    "duckduckgo": DuckDuckGoSearchProvider,
}
service = SearchService([provider_map[p]() for p in providers])
```

---

### 16. `_run_single_provider` 计时包含 SearchService 开销

**文件**: `src/evaluation/search_eval.py:249-269`

**问题描述**:  通过 `service.parallel_search(provider_names=[name])` 测量单个 provider 的运行时间，计时包含了 SearchService 的 provider 选择、结果去重等框架开销。

**影响**:  单个 provider 的 `duration_ms` 与 pure provider 搜索时间存在偏差，性能对比基准不纯粹。

**修复建议**:  直接调用 `provider.search(request)` 以获取纯 provider 时间，或在文档中明确说明计时包含框架开销。

---

### 17. HttpFetchProvider 状态码处理遗漏

**文件**: `src/providers/fetch/http.py:45-58`

**问题描述**:  4xx 错误（404、403 等）未被显式处理。代码先检查 5xx，然后检查 content-type。如果服务器返回 404 且 Content-Type 为 `text/html`，会继续解析 HTML 错误页面为 Markdown。

**失败场景**:  `fetch("https://example.com/nonexistent")` → 返回 404 HTML 错误页面 → 被正常解析为 Markdown → 用户得到无意义的错误页面内容而非明确的 404 错误。

**修复建议**:  在 content-type 检查之前添加 4xx 错误处理：

```python
if response.status_code >= 400:
    raise ProviderError(
        error_type=ErrorType.INVALID_RESPONSE,
        provider=self.name,
        message=f"HTTP fetch returned {response.status_code}.",
        http_status=response.status_code,
    )
```

---

## 修复优先级建议

| 优先级 | 问题编号 | 问题 | 预估工作量 |
|-------|---------|------|-----------|
| P0 | #1 | AsyncClient 资源泄漏（app.py） | 小 |
| P0 | #2 | FetchService gather 失败导致全部丢失 | 小 |
| P0 | #3 | Jina reader URL 未编码 | 小 |
| P0 | #4 | DuckDuckGo 无超时 | 小 |
| P0 | #5 | Provider 内部 client 泄漏 | 中 |
| P1 | #7 | URL 归一化不一致 | 小 |
| P1 | #8 | Markdown 表格未转义 | 小 |
| P1 | #10 | 日志泄露搜索结果 | 小 |
| P1 | #6 | MCP tool 参数类型不一致 | 小 |
| P1 | #11 | looks_blocked 误报 | 中 |
| P2 | #14 | 测试覆盖不足 | 大 |
| P2 | #17 | HttpFetchProvider 4xx 处理 | 小 |
| P2 | #9 | CancelledError 处理 | 小 |
| P3 | #12, #13, #15, #16 | 其他轻微问题 | 小 |

---

## 附录: 涉及文件清单

- `src/app.py`
- `src/api/mcp_full.py`
- `src/config.py`
- `src/errors.py`
- `src/schemas.py`
- `src/services/search_service.py`
- `src/services/fetch_service.py`
- `src/providers/search/tavily.py`
- `src/providers/search/exa.py`
- `src/providers/search/duckduckgo.py`
- `src/providers/fetch/http.py`
- `src/providers/fetch/jina.py`
- `src/evaluation/search_eval.py`
- `src/utils/content_detection.py`
