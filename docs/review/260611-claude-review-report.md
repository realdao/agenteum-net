# Agenteum Net 代码审查报告（2026-06-11）

**审查对象：** https://github.com/realdao/agenteum-net （HEAD `cfe0862`，共 24 个提交，版本 0.1.0）
**审查方式：** 全量逐行静态审查（源码 + 测试 + 部署脚本 + 设计文档），关键存疑行为对照官方 API 文档核实（Exa 已查证）。本机无 Python 3.11+/uv 环境，**未运行测试套件与 ruff**，结论均来自代码路径回溯。
**审查范围：** src/（app、config、schemas、errors、api、services、providers、utils、evaluation、resources）、tests/（unit、smoke、e2e）、deploy/（linux、windows）、pyproject、设计文档

**项目概览：** HTTP-only 的 MCP 服务器，向本地 agent 客户端暴露 `search` / `parallel_search` / `fetch` 三个工具。搜索链 Tavily → Exa → DuckDuckGo（顺序回退），抓取链 HTTP+MarkItDown → Jina Reader 回退（x.com/twitter.com 直走 Jina）。无认证，默认绑 127.0.0.1。约 1700 行源码 + 1400 行测试。

---

## 一、严重（核心工具在常见配置下不可靠，建议立即修复）

### S1. fetch 批量抓取：未配 JINA_API_KEY 时，一个 URL 触发 Jina 回退就让**整批**失败，且与文档承诺直接矛盾

- **位置：** [fetch_service.py:62-63](src/services/fetch_service.py:62)（`CONFIG_ERROR`/`AUTH_ERROR` 重新抛出）、[fetch_service.py:34](src/services/fetch_service.py:34)（`asyncio.gather` 未设 `return_exceptions`）
- **机制：** `_fetch_with_item_error` 对 Jina 的 `CONFIG_ERROR`/`AUTH_ERROR` 选择重新抛出而非折叠为单项错误；该异常穿透 `gather` 使整个 `fetch` 工具调用报错——**所有 URL（包括已成功抓取的）的结果全部丢弃**，其余仍在执行的抓取协程被遗弃（不会取消，继续空跑到结束，结果作废）。
- **触发：** `.env.example` 默认 `JINA_API_KEY=`（空）。此时批量抓 10 个 URL，只要满足任意一条就整批失败：① 其中有 x.com/twitter.com 链接（强制走 Jina）；② 任意一个 URL 的 HTTP 抓取命中 `BLOCKED`/`EMPTY_CONTENT`/`TIMEOUT`/`NETWORK`/`PROVIDER_5XX`/`INVALID_RESPONSE`（全部会回退 Jina）。临时网络抖动都在此列，与 S2 的误报叠加后触发面极大。
- **文档矛盾：** [fetch-guide.md](src/resources/fetch-guide.md) 明确承诺 "Individual failures are reported in the matching result item and **do not fail the whole batch**"。设计文档第 443 行写的是 config_error "no fallback"——不回退 ≠ 整批失败，按 spec 也应折叠为该项的 item error。
- **修复：** `_fetch_with_item_error` 不再重抛，统一返回 `status:"error"` 的单项结果（错误信息里保留 "JINA_API_KEY is not configured"，agent 仍能看到原因）；同时 `fetch()` 的 `gather` 加 `return_exceptions=True` 兜底，把任何意外异常折叠为对应 URL 的 item error。补一个"批量中一个 URL 触发 Jina 且无 key"的用例。

### S2. `looks_blocked` 强标记对**整页 HTML** 匹配，误报面巨大：所有 React/Vue SPA、提及 captcha 的正文、标题含 "Cloudflare" 的文章全部被判"被屏蔽"

- **位置：** [content_detection.py:5-14](src/utils/content_detection.py:5)（强标记表）、[content_detection.py:31-32](src/utils/content_detection.py:31)（`combined` 含完整 html）、[http.py:68](src/providers/fetch/http.py:68)（转换前的首次检查）
- **机制（三个独立误报源）：**
  1. 强标记 `"enable javascript"` 对全文匹配——CRA/Vite/Next 等脚手架默认输出 `<noscript>You need to enable JavaScript to run this app.</noscript>`，**几乎所有 SPA 首页**命中；
  2. 强标记 `"captcha"`/`"bot detection"` 对全文匹配——页面里只要有 reCAPTCHA 脚本引用（评论区、登录框）或正文讨论验证码就命中；
  3. [http.py:68](src/providers/fetch/http.py:68) 的首次检查发生在 Markdown 转换**之前**，`markdown_text=""`，弱标记的长度条件 `len("") < 500` 恒为真——于是 `<title>` 含 "cloudflare" 或 "forbidden" 的页面（如 Cloudflare 官方博客每篇文章）直接判 `BLOCKED`，连转换的机会都没有。现有测试 `test_blocked_detector_avoids_ordinary_cloudflare_article` 传入了长 markdown，恰好测不到这条真实代码路径。
- **后果：** 配了 Jina key → 上述页面全部绕道 Jina（白花钱、变慢，Jina 渲染 SPA 倒是因祸得福）；没配 key → 与 S1 叠加，**整批 fetch 失败**。
- **修复：** 强标记只对 `title` + 转换后 markdown 的前若干字符匹配（不要扫原始 HTML 全文）；首次（html-only）检查只用强标记于 title，弱标记的长度条件必须基于转换后内容；测试补 noscript SPA 和 "cloudflare 标题 + html-only" 两个用例。

---

## 二、高（功能默默劣化 / 现实场景大概率踩坑）

### H1. Exa 搜索结果**永远没有摘要**：请求未带 `contents`，而测试用假数据掩盖了这一点

- **位置：** [exa.py:36-39](src/providers/search/exa.py:36)（payload 只有 `query`+`numResults`）、[exa.py:87](src/providers/search/exa.py:87)（snippet 取 `text`/`summary`/`highlights`）
- **核实：** Exa 官方文档（本次审查查证）：`contents` 不传时 `text`/`highlights`/`summary` **默认全部关闭**，响应只有 title/url/publishedDate/score。因此 snippet 链恒为 `None`——Exa 出场时（search 回退到它、或 parallel_search 含它）结果只有标题+URL，对 LLM 几乎没有信息量，付费调用没拿到应有价值。
- **测试掩盖：** [test_exa.py:24](tests/unit/providers/search/test_exa.py:24) 的 fake 响应自带 `"text": "Protocol text"`，固化了一个真实 API 不会出现的形态；search-eval 只统计 URL 数，也发现不了。
- **修复：** payload 增加 `"contents": {"text": {"maxCharacters": 500}}`（或 `highlights`）；fake 数据改为与真实默认响应一致 + 单独一个带 contents 的用例；search-eval 增加 snippet 覆盖率指标。

### H2. 开箱即坏：不配任何 key 时 `search` 工具**完全不可用**，尽管免费的 DuckDuckGo 就在链尾

- **位置：** [tavily.py:40-45](src/providers/search/tavily.py:40)（无 key → `CONFIG_ERROR`）、[search_service.py:19-26](src/services/search_service.py:19)（`CONFIG_ERROR` 不在回退集合）、[search_service.py:54-55](src/services/search_service.py:54)（直接抛出）
- **机制：** `.env.example` 全空 key 起服务 → 每次 `search` 都报 "TAVILY_API_KEY is not configured."，永远到不了 DuckDuckGo。而 `parallel_search` 对同样的错误却能正常降级（错误进 `errors` 数组、返回 DDG 结果）——**同一工具族行为不一致**，工具描述 "Search the web through Tavily, Exa, and DuckDuckGo fallback providers" 给 agent 的预期也与实际不符。
- **辨析：** 设计文档第 302 行明确 "config_error: do not fallback"（配置坏了要响亮失败，合理）。但"**从未配置**"和"配置了但坏了"是两码事——前者是用户的有意选择，不该按故障处理。
- **修复：** 在 [app.py:32-39](src/app.py:32) 组装链时直接**跳过没有 key 的 provider**（启动日志说明 "Tavily disabled: no API key"），三个全缺时只挂 DuckDuckGo。这既修好开箱体验，又完整保留"有 key 但 401 → 响亮失败"的 spec 语义。

### H3. fetch 链路健壮性：响应大小无上限、Markdown 转换同步阻塞整个事件循环、超时是"每次读"而非总时长

- **位置：** [http.py:29](src/providers/fetch/http.py:29)（全量缓冲）、[http.py:77](src/providers/fetch/http.py:77)（同步转换）、[app.py:29](src/app.py:29)（`timeout=20`）
- **三个问题：**
  1. **无大小上限**：`Content-Type: text/html` 的任意大响应会被完整读进内存，转换后的整页 Markdown 原样进 MCP 响应（一次塞爆 agent 上下文）；
  2. **事件循环阻塞**：MarkItDown（BeautifulSoup 解析）是 CPU 密集的同步调用，直接在 async 路径里执行——大页面解析期间**整个服务的所有并发请求都冻结**；
  3. **超时语义**：`httpx.AsyncClient(timeout=20.0)` 是 connect/read/write 各 20s 的 per-operation 语义，read 超时按"两次收包间隔"计——慢速滴流的服务器可以让单次抓取远超 20s 不触发超时。
- **修复：** 流式读取并在如 3MB 处截断（超限按 `UNSUPPORTED_CONTENT` 或截断标记处理）；`asyncio.to_thread(self.converter.html_to_markdown, ...)`；可选增加返回内容的最大字符数配置。三处都是小改动。

### H4. SSRF：`fetch` 可抓取任意回环/内网/云元数据地址，重定向亦不设防

- **位置：** [http.py:29](src/providers/fetch/http.py:29)（无目标过滤）、[app.py:29](src/app.py:29)（`follow_redirects=True`）
- **场景：** 即便纯本地使用，LLM agent 被提示注入后可被诱导 `fetch("http://169.254.169.254/latest/meta-data/")`（云 VM 凭证）、`http://127.0.0.1:<port>` 内部服务、内网管理面板；若设了 `AGENTEUM_ALLOW_REMOTE=true` 绑 0.0.0.0，则等于向局域网开放一个**无认证 SSRF 代理**。外部站点 302 到内网地址同样生效。
- **辨析：** spec 定位"trusted local"，README 也声明了无认证风险——这是知情权衡；但 fetch 的目标过滤与"服务绑哪"是两层防线。
- **修复：** 默认解析目标主机后拒绝 loopback/private/link-local（重定向改为手动跟随并逐跳校验），提供 `AGENTEUM_ALLOW_PRIVATE_FETCH` 显式放行开关。

### H5. Linux 部署：`ProtectHome=true` 与"项目克隆在家目录"的默认场景冲突，服务大概率根本起不来

- **位置：** [agenteum-net.service:26](deploy/linux/agenteum-net.service:26)（`ProtectHome=true`）、[agenteum-net.service:14](deploy/linux/agenteum-net.service:14)（`ExecStart=%VENV_BIN%/agenteum-net`）、[install-service.sh:6](deploy/linux/install-service.sh:6)（`PROJECT_DIR` 取脚本所在仓库路径）
- **机制：** `ProtectHome=true` 使该 unit 完全看不到 `/home`、`/root`。而安装脚本把 ExecStart、WorkingDirectory、`.env`、`.venv` 全指向仓库路径——典型用法（clone 在 `/home/<user>/`）下服务启动即 `status=203/EXEC`；root 部署在 `/root` 同样被屏蔽。只有部署到 `/opt` 等路径才能工作，但脚本和文档都没有此要求。
- **附带：** 脚本只 `chown` 了 logs 目录；root 场景下新建的 `agenteum` 系统用户对 `.venv` 的读权限也未保证。`StandardOutput=append:` 写的日志文件**没有任何轮转**（Windows 端 NSSM 倒是设了 10MB 轮转），DEBUG 级别下会无限增长。
- **修复：** `ProtectHome=read-only`（保留加固且能读 home 下的项目），或脚本检测项目位于 `/home` 时给出明确提示；为 logs 补 logrotate 配置或改用 journald。

---

## 三、中

### M1. e2e 测试默认被 pytest 收集：会**强杀占用 8765 端口的任意进程**，并真实调用 opencode/LLM/外部网络

- **位置：** [pyproject.toml:42](pyproject.toml:42)（`testpaths=["tests"]` 含 e2e）、[test_opencode_mcp.py:51](tests/e2e/test_opencode_mcp.py:51)（`_ensure_port_free` 对 8765 监听者 SIGTERM / `taskkill /F`）、[test_opencode_mcp.py:151](tests/e2e/test_opencode_mcp.py:151)（fixture 硬编码 8765）
- **问题：** 装有 opencode 的机器上跑 `uv run pytest` 会：① 杀掉正在运行的 agenteum-net 生产实例（或任何恰好占 8765 的无关进程）；② 通过 opencode 触发真实 LLM 调用与真实搜索/抓取（花钱，单测试最长 120s）。这与 [README:62](README.md:62) "Default automated tests do not call real ... endpoints" 直接矛盾。讽刺的是文件里定义了 [`_free_port()`](tests/e2e/test_opencode_mcp.py:22) 却没用上（死代码）。
- **修复：** 给 e2e 加 `@pytest.mark.e2e` 并在 pyproject 设 `addopts = "-m 'not e2e'"`；server fixture 改用 `_free_port()` 起服务，彻底删掉杀进程逻辑。

### M2. HTTP 4xx 被当成功内容返回，`FetchResult` 又没有 http_status 字段

- **位置：** [http.py:45-58](src/providers/fetch/http.py:45)（仅处理 ≥500 与 content-type）
- **机制：** 404/403/410 的 HTML 错误页只要够长、不踩 blocked 标记，就以 `status:"ok"` 返回错误页正文；agent 拿到一篇"页面不存在"的 Markdown 却没有任何信号判断这不是目标内容。
- **修复：** `FetchResult` 增加 `http_status` 字段（schema 小改）；4xx 至少标注状态码，或直接映射为 item error。

### M3. 三个 `httpx.AsyncClient` 永不关闭

- **位置：** [app.py:28-30](src/app.py:28)（创建）、[app.py:52-55](src/app.py:52)（lifespan 只托管 MCP session manager）
- **影响：** 长驻进程无感；但 smoke 测试等每次 `create_app()` 都会泄漏三个连接池（ResourceWarning），嵌入/热重载场景累积。
- **修复：** lifespan 退出时依次 `aclose()` 三个 client。

### M4. 错误类型映射失真：Jina 429 与 ddgs 异常都被折叠成泛化的 `provider_error`

- **位置：** [jina.py:66-73](src/providers/fetch/jina.py:66)（429 落入通用分支，应为 `RATE_LIMITED`）、[duckduckgo.py:33-39](src/providers/search/duckduckgo.py:33)（ddgs 的 `RatelimitException`/`TimeoutException` 被宽 except 吞掉）
- **影响：** DDG 处于链尾时顺序回退不受影响，但 `parallel_search` 的 `errors` 报告失真（DDG 限流极常见）；未来调整链序或把错误类型用于重试决策时就是暗雷。
- **修复：** Jina 分支补 429；DDG 捕获 ddgs 具体异常类型并映射 `RATE_LIMITED`/`TIMEOUT`。

### M5. 打包反模式：安装后的顶层包名是 `src`，且向 PATH 注册了名为 `main` 的可执行

- **位置：** [pyproject.toml:36](pyproject.toml:36)（`include = ["src*"]`，全部 import 均为 `from src.x import ...`）、[pyproject.toml:25](pyproject.toml:25)（`main = "src.app:main"`）
- **影响：** `pip install` 后会占据全局唯一的 `src` 包名（与任何同样打包方式的库冲突，无法与其他项目共存于同一环境）；venv 的 bin 里多出一个叫 `main` 的命令。本地 `uv run` 场景能跑，要分发必改。
- **修复：** 包重命名为 `agenteum_net`（目录平移 + import 批量替换，机械工作）；删除 `main` 脚本入口。

---

## 四、低

- **L1. URL 回显被改写：** [schemas.py:84-87](src/schemas.py:84) 用 `AnyHttpUrl` 校验后 `str()` 回显，pydantic 会规范化（`https://example.com` → `https://example.com/`，[test_mcp_full.py 已固化此行为](tests/unit/api/test_mcp_full.py)）。调用方按原始字符串对账 `results[].url` 会失配。建议校验归校验、响应回显原始输入。另：一个 URL 非法会让整批 fetch 直接 422（输入校验，可接受，但 fetch-guide 未说明）。
- **L2. time_range/topic 静默丢弃：** Exa 完全不发这两个参数（其实 Exa 有 `startPublishedDate` 可支持 time_range）；Tavily 对非法 topic 静默忽略（[tavily.py:55](src/providers/search/tavily.py:55)）。文档说 "best-effort"，但 [providers-capabilities.md](src/resources/providers-capabilities.md) 不写明谁支持什么，agent 无从判断。
- **L3. 死代码/赘余抽象：** [utils/logging.py](src/utils/logging.py) 的 `get_logger` 无人使用；[api/transport.py](src/api/transport.py) 是单行透传包装。
- **L4. search-eval 小问题：** [`--limit` 文案说 1..49](src/evaluation/search_eval.py:277) 但内置仅 12 条查询，13–49 静默截断；eval 的 [`_normalize_url`](src/evaluation/search_eval.py:287)（仅 rstrip）与服务端去重规则（defrag+rstrip）不一致，统计口径有细微偏差。
- **L5. 文档/版本不一致：** providers-capabilities.md 把三个 key 列为 "Required environment variables"（实际全部可选）；README 通篇称 "v1.0" 而 pyproject 与 `src/__init__.__version__` 是 0.1.0（且版本号双源维护）。
- **L6. 部署细节：** Windows 脚本从 nssm.cc 下载 NSSM 2.24（2014 年发布）无哈希校验；`nssm remove` 在 `Stop-Service` 之前执行；Linux 安装脚本不检查 root 就写 `/etc`（`set -e` 兜底但报错不友好）。
- **L7. 日志体积：** DEBUG 级会把抓取的整页 Markdown 与完整搜索结果写日志（README 有声明，属知情设计），结合 H5 提到的"systemd append 无轮转"需要注意磁盘。

---

## 五、测试覆盖盲区（与上述发现一一对应）

测试纪律本身很好（fake/MockTransport、无网络依赖、断言具体），但盲区恰好都压在真实故障路径上：

| 盲区 | 对应发现 |
|---|---|
| fetch_service 没有"Jina 抛 CONFIG_ERROR/AUTH_ERROR"路径的用例 | S1 |
| content_detection 没有 noscript SPA、"cloudflare 标题 + html-only 首次检查"用例 | S2 |
| test_exa 的 fake 响应带真实 API 默认不返回的 `text` 字段 | H1 |
| http provider 没有任何 4xx 用例 | M2 |
| 没有"批量 fetch 部分失败"的集成用例去对照 fetch-guide 的承诺 | S1 |

---

## 六、亮点

- **分层干净：** spec 明文 "Providers must not implement fallback policy" 并被严格遵守——策略全在 service 层，provider 只做协议翻译；依赖注入贯穿，测试因此全程无 monkey-patch。
- **错误处理框架成熟：** 统一的 `ErrorType` 分类学 + `ProviderError` + `safe_repr()` 秘钥脱敏/载荷截断（[errors.py](src/errors.py)），且脱敏有专门测试。
- **安全姿态明确：** 默认 loopback，远程绑定需要显式 `ALLOW_REMOTE` 双开关 + 启动 WARNING + README/spec 三处声明（虽然 H4/H5 显示纵深还差一层）。
- **工程化认真：** 3500 行设计文档+实施计划，fallback 矩阵按错误类型逐条写明；commit 历史干净规范（曾有 "remove dead code and fix type issues from review" 这类自查提交）；ruff 规则集（E/F/I/UP/B/SIM）不算敷衍。

## 七、总体评价与修复顺序

这个代码库的**骨架质量在水准之上**：结构、测试纪律、错误分类、文档完整度都好于绝大多数同体量个人项目。问题集中在三处：**fetch 链路对真实世界网页的鲁棒性**（S2 误报 → S1 整批失败 → H3 无上限/阻塞，三者会串联放大）、**默认无 key 配置下的开箱体验**（H2、S1 同根）、以及**部署脚本未经真实路径验证的痕迹**（H5）。服务本身无状态，不存在数据丢失/损坏类风险。

建议修复顺序（前四项改动都很小）：

1. **S1 + S2**（同在 fetch 链路，一次 PR：item-error 化 + 收紧 blocked 判定，连带补测试）
2. **H1**（payload 加一行 `contents`，立即提升 Exa 价值）
3. **H2**（组装链时跳过未配置的 provider）
4. **M1**（e2e 加 marker，防止误杀生产进程）
5. **H3**（流式上限 + `to_thread`）
6. **H5**（若实际使用 Linux 部署）/ **H4**（若会开 0.0.0.0 或跑在云 VM 上）
7. 其余 M/L 顺手清理
