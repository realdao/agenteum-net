# Agenteum Net 代码审查报告·第二轮（2026-06-11）

**审查对象：** https://github.com/realdao/agenteum-net （HEAD `cfe0862`，与第一轮一致，期间无新提交）
**审查方式：** 独立重审。先对第一轮（[代码审查报告-2026-06-11.md](代码审查报告-2026-06-11.md)）全部 19 项结论做代码路径复核，再对第一轮覆盖较浅的区域增量深挖：依赖库真实 API 联网核验（ddgs 9.14.4、markitdown 0.1.5 源码、Exa API 文档）、MCP 工具 schema 生成机制、e2e 测试逐行细读、evaluation 边界路径、日志与 systemd 指令细节。本机仍无 Python 3.11+/uv，未运行测试套件。
**本轮结果概览：** 第一轮 19 项**全部复核属实，零勘误**，其中 2 项有补强；新增 **1 高、2 中、7 低** 共 10 项发现；另有 4 个疑点经核验**排除**（含 1 个本轮自己提出又证伪的假设）。

---

## 一、第一轮结论复核

| 项 | 复核结果 |
|---|---|
| S1 fetch 整批失败 | **属实，且补强**：除"无 JINA_API_KEY"外，**配了 key 但 key 过期/被 401** 同样命中——[jina.py:59-65](src/providers/fetch/jina.py:59) 把 401/403 映射为 `AUTH_ERROR`，[fetch_service.py:62](src/services/fetch_service.py:62) 对 `AUTH_ERROR` 同样重抛 → 整批失败。即付费用户也有触发路径 |
| S2 looks_blocked 误报 | 属实（noscript SPA / 全文 captcha / cloudflare 标题三条路径逐一回溯确认） |
| H1 Exa 无摘要 | 属实（Exa 文档第一轮已核验：`contents` 不传则 text/highlights/summary 默认全关） |
| H2 无 key 开箱即坏 | 属实，且衍生出更严重的"部分配置"变体，见本轮 **N1** |
| H3 大小无上限/事件循环阻塞/超时语义 | 属实 |
| H4 SSRF | 属实 |
| H5 systemd ProtectHome | 属实（另见本轮 N10 的连锁：撞启动限制后 unit 进入永久 failed） |
| M1 e2e 杀进程/真实调用 | 属实，`_free_port` 死代码经 grep 确认全仓库零调用；本轮另发现 e2e 更深的问题，见 **N3** |
| M2 4xx 当成功 | 属实 |
| M3 client 不关闭 | 属实 |
| M4 错误映射失真 | 属实（ddgs 异常类型本轮经 PyPI 核验确实存在专门的限流/超时异常可供映射） |
| M5 打包 `src`/`main` | 属实 |
| L1–L7 | 全部属实 |

---

## 二、本轮新增发现

### N1.（高）"只配 Tavily key"的最常见付费配置下，Tavily 一次限流/超时就让 search 报出误导性错误，DuckDuckGo 永远兜不了底

- **位置：** [search_service.py:43-55](src/services/search_service.py:43)（回退循环）、[exa.py:29-34](src/providers/search/exa.py:29)（无 key → `CONFIG_ERROR`）
- **机制：** 用户只配 `TAVILY_API_KEY`（最现实的单一付费配置）。Tavily 命中 429/超时/5xx（都在可回退集合）→ 链路推进到 Exa → Exa 因无 key 抛 `CONFIG_ERROR` → 不在 `FALLBACK_ERROR_TYPES` → **整个 search 立即失败**。两个糟糕后果：① 链尾免费可用的 DuckDuckGo 永远没机会兜底；② agent 看到的报错是 *"EXA_API_KEY is not configured."*——用户明明配好了 Tavily，错误却指向一个从没打算用的服务商，极具误导性。
- **与 H2 的关系：** H2 说的是"全不配则 search 不可用"；N1 说明**部分配置同样脆弱**——回退链的健壮性恰好在最需要它的时刻（上游故障）被未配置的中间环节打断。
- **修复：** 与 H2 同一个修法即可一并解决——[app.py:32-39](src/app.py:32) 组装时跳过无 key 的 provider，链变成 Tavily → DuckDuckGo，回退语义恢复正常。

### N2.（中）MCP 工具的 inputSchema 不携带任何约束：枚举、上下界、数量限制对 agent 全部不可见，只能靠运行时报错试探

- **位置：** [mcp_full.py:22-27](src/api/mcp_full.py:22)（`time_range: str | None`、`max_result: int = 10`）、[mcp_full.py:96](src/api/mcp_full.py:96)（`urls: list[str]`）
- **机制：** FastMCP 从**函数签名**生成工具的 JSON Schema；而真正的约束（`TimeRange` 枚举、`ge=1 le=20`、`min_length=1 max_length=10`、`AnyHttpUrl`）全部定义在函数体内部才构造的 `SearchRequest`/`FetchRequest` 上（[schemas.py:14-27](src/schemas.py:14)、[schemas.py:83-87](src/schemas.py:83)）。于是 agent 拿到的 schema 是"任意字符串/任意整数/任意长度数组"，传 `time_range="hour"`、`max_result=50`、11 个 URL 都要等到 ValidationError 才知道错——浪费一轮工具调用，错误文案还是 pydantic 原始格式。
- **修复：** 把约束上移到签名：`time_range: TimeRange | None = None`、`max_result: Annotated[int, Field(ge=1, le=20)] = 10`、`urls: Annotated[list[str], Field(min_length=1, max_length=10)]`——FastMCP 会把 pydantic 元数据带进 inputSchema；单行 docstring 也建议补上取值说明（MCP resources 里的指南写得很好，但多数客户端不会主动读 resource）。

### N3.（中）e2e 的"等服务就绪"是假的：固定干烧 10 秒，且 stdout/stderr 管道全程无人排水——日志一多服务器会被管道缓冲区卡死

- **位置：** [test_opencode_mcp.py:92-104](tests/e2e/test_opencode_mcp.py:92)（`_wait_for_server`）、[test_opencode_mcp.py:158-160](tests/e2e/test_opencode_mcp.py:158)（`stdout=PIPE, stderr=PIPE`）
- **机制（两个问题）：**
  1. 函数 docstring 写 *"Wait until uvicorn logs 'Application startup complete'"*，但循环体只检查 `proc.poll()` 和 `sleep(0.2)`，**从不读取输出、没有任何成功分支**——每次必然烧满 `SERVER_START_TIMEOUT=10` 秒（外加 fixture 再睡 1 秒）才开始测试；
  2. 服务器进程的 stdout/stderr 接到 PIPE 后，整个测试期间**没有任何代码读取**（只在进程死亡后才 `read()`）。uvicorn 访问日志 + 应用 INFO 日志（每次工具调用都打 query/结果摘要）持续写入 stderr，一旦累计超过 OS 管道缓冲（约 64KB），**服务器进程会在写日志时永久阻塞**——表现为 opencode 等到 120 秒超时、报错信息毫无指向性。`AGENTEUM_LOG_LEVEL=DEBUG`（整页抓取内容进日志）时几乎必现。
- **修复：** 就绪检测改为轮询 TCP 端口连通（或起一个后台线程逐行读 stderr、匹配 startup 标记后继续持续排水）；或干脆 stdout/stderr 重定向到临时文件，失败时再读文件取证。与第一轮 M1（marker、`_free_port`）一并整改。

### N4.（低）spec 明文要求的"invalid_response 经安全表示记日志"从未实现；`safe_repr()` 在生产代码中零调用

- **位置：** [errors.py:72-80](src/errors.py:72)（`safe_repr` 定义）、[search_service.py:64-73](src/services/search_service.py:64)（回退日志只记 reason）
- **依据：** 设计文档 §304 写明 *"`invalid_response`: fallback immediately and **log the malformed provider response through the safe error representation**"*，§477 也把 `safe_repr()` 列为必备。实现里精心写了脱敏/截断逻辑并配了测试，但全仓库没有任何日志调用用到它——服务商返回畸形响应时，除了 reason 字符串什么都查不到；search 全链失败抛出最后一个错误时，前面积累的 `fallbacks` 记录也随异常一起丢弃，排障只见最后一环。
- **修复：** 回退分支按 spec 补 `logger.warning(..., extra={"error": exc.safe_repr()})`；全链失败的最终异常附带 fallback 历史。

### N5.（低）部署形态下所有日志文件**没有任何时间戳**

- **位置：** [app.py:69-70](src/app.py:69)（`logging.basicConfig(level=...)` 未设 format）、[agenteum-net.service:22-23](deploy/linux/agenteum-net.service:22)（`StandardOutput=append:` 直写文件，绕过 journald）
- **机制：** `basicConfig` 默认格式是 `LEVEL:name:message`，uvicorn 自带格式也不含 asctime。journald/NSSM 控制台场景有外部时间戳兜底，但 Linux unit 用 `append:` 直写文件、NSSM 也是裸文件重定向——最终 `logs/*.log` 里**完全没有时间信息**，与 commit 3c5897e"把日志交给 NSSM/systemd 管理"的意图相悖（轮转和时间戳都没接住，轮转缺失已在第一轮 H5/L7 提及）。
- **修复：** `basicConfig(format="%(asctime)s %(levelname)s %(name)s %(message)s", ...)`，并给 uvicorn 传带时间戳的 log_config；或 Linux 改回 journald。

### N6.（低）search 顺序回退链没有总时限预算；DDG 干脆不传超时

- **位置：** [app.py:28](src/app.py:28)（仅 per-request 15s）、[duckduckgo.py:42](src/providers/search/duckduckgo.py:42)（`DDGS()` 未传 timeout，吃库默认值）
- **机制：** 最坏路径 Tavily 15s 超时 → Exa 15s 超时 → DDG（库默认超时）≈ **35s+**；fetch 更甚：HTTP 20s 失败 → Jina 30s ≈ 单 URL 50s。MCP 客户端常见 60s 工具超时，贴边运行，客户端一旦超时还看不到任何部分结果。
- **修复：** 给链路加总预算（如 `asyncio.timeout(30)` 包住 search 整链），DDG 显式传 timeout。

### N7.（低）search-eval 传未知 provider 名时以裸 ValidationError 崩溃而非友好报错

- **位置：** [search_eval.py:106-119](src/evaluation/search_eval.py:106)（`SearchProviderError(provider=run.provider, ...)`）
- **机制：** `--providers foo` → 单 provider 运行被 `except ProviderError` 接住记为 `ProviderRun(provider="foo", error="invalid_request")` → 主流程 `parallel_search` 再抛 → 走 `empty_parallel_response_from_provider_runs` → 构造 `SearchProviderError(provider="foo")` → `provider` 字段是 `Literal["tavily","exa","duckduckgo"]` → **pydantic ValidationError 直接炸出 traceback**。现有测试只喂合法名字（[test_search_eval.py](tests/unit/evaluation/test_search_eval.py)），盖不住这条路。
- **修复：** `_parse_providers` 阶段就校验白名单并 `parser.error(...)` 友好退出。

### N8.（低）`parallel_search` 的 providers 参数不去重：传 `["tavily","tavily"]` 会对同一服务商发两次计费请求

- **位置：** [search_service.py:144-159](src/services/search_service.py:144)
- **影响：** 结果会被 URL 去重掩盖，但 API 调用/计费/限流配额实打实翻倍；LLM 生成参数时偶尔会重复。修复：选择时按序去重。

### N9.（低）地区取向自相矛盾且都不可配：DDG 默认 `us-en`，fetch 头硬编码 `zh-CN`

- **位置：** [duckduckgo.py:44-48](src/providers/search/duckduckgo.py:44)（未传 region，ddgs 9.x 默认 `us-en`，本轮已核验）、[headers.py:10](src/utils/headers.py:10)（`Accept-Language: zh-CN,zh;q=0.9`）
- **影响：** 搜索结果偏英文美区、抓取却向多语言站点要中文版，两者方向相反；中文查询在 DDG 上效果也受 region 影响。修复：增加 `AGENTEUM_LOCALE`（或分开两个）配置，贯通 search region 与 fetch Accept-Language。

### N10.（低）systemd 单元用了 legacy 位置的限速指令，且与 H5 连锁成"3 次 5 秒后永久趴下"

- **位置：** [agenteum-net.service:17-19](deploy/linux/agenteum-net.service:17)（`StartLimitInterval`/`StartLimitBurst` 写在 `[Service]`；现代 systemd 规范名是 `[Unit]` 段的 `StartLimitIntervalSec`，旧名仅作兼容别名保留）
- **连锁：** 若 H5 的 `ProtectHome` 启动失败成立：`Restart=always` + `RestartSec=5` + Burst 3 → 约 15 秒内连挂 3 次 → unit 进入 failed，不再重试。指令本身能用，迁移到规范位置即可。

---

## 三、本轮核验后排除的疑点（无需修复，记录以免后续重复怀疑）

1. **GBK/非 UTF-8 中文页面经 MarkItDown 二次解码乱码——证伪。** 怀疑链是：httpx 正确解码 GBK → 代码重编码为 UTF-8 字节（[markdown.py:14](src/utils/markdown.py:14)）→ 若 BeautifulSoup 按页面 `<meta charset=gbk>` 声明解码就会乱码。核验 markitdown 0.1.5 源码：上游用 **charset_normalizer 对实际字节做内容检测**（会测出 UTF-8），HtmlConverter 再以 `BeautifulSoup(stream, from_encoding=检测值)` **显式覆盖** meta 声明——链路安全。
2. **ddgs 9.14.4 API 兼容性——通过。** `DDGS().text(query, timelimit=, max_results=)` 与 [duckduckgo.py:44-48](src/providers/search/duckduckgo.py:44) 的调用完全吻合（PyPI 官方文档核验）；fake 测试假设的签名与真实一致。
3. **markitdown `convert_stream(file_extension=, url=)`——兼容但已标记 Deprecated。** 0.1.x 仍接受这两个 kwarg（注释明确 "Deprecated -- use stream_info"）。pyproject 钉死 `<0.2` 所以当前安全；将来升级需迁移到 `stream_info=StreamInfo(extension=".html", url=...)`。
4. **`/mcp/full` 挂载与 MCP 生命周期——已正确处理。** commit d041b8b 用 `lifespan_context` 显式托管子应用生命周期（[app.py:52-55](src/app.py:52)），e2e 与手动冒烟文档显示端点实际可用，不立案。

---

## 四、测试覆盖补充盲区（在第一轮 5 条之上新增）

| 盲区 | 对应发现 |
|---|---|
| 没有"只配 Tavily key + Tavily 限流"的链路用例（现有 `test_quota_exhausted_falls_back_to_exa` 里 Exa 是配置好的 fake） | N1 |
| e2e 无就绪探测断言、无长日志场景（管道排水）验证 | N3 |
| search-eval 未知 provider 名无用例 | N7 |
| 工具层没有任何"schema 约束对 agent 可见性"的回归断言（如 inputSchema 含 enum/maximum） | N2 |

---

## 五、两轮合并后的修复优先级（更新版）

1. **S1 + S2**（fetch 链路一次 PR：item-error 化 + 收紧 blocked 判定 + 补测试）
2. **H2 + N1**（同一个修法：组装时跳过未配置 key 的 provider——一行过滤解决两个发现）
3. **H1**（Exa payload 加 `contents`，一行）
4. **M1 + N3**（e2e 卫生：marker 默认排除 + `_free_port` 真用上 + 就绪探测/管道排水 + 删杀进程逻辑）
5. **H3**（流式大小上限 + `to_thread` 包转换）
6. **N2**（约束上移到工具签名，agent 体验立竿见影）
7. **H5 + N10**（若实际用 Linux 部署）/ **H4**（若会开 0.0.0.0 或跑在云 VM）
8. 其余 M/L/N 顺手清理（M2 http_status、M3 aclose、M4 错误映射、N4 safe_repr 接线、N5 日志时间戳、M5 打包改名……）

## 六、第二轮总体结论

第一轮的判断经独立复核全部成立：**骨架质量好，风险集中在 fetch 真实世界鲁棒性与"非满配 key"场景的回退链脆弱性**。本轮新增发现里最值得重视的是 N1（付费用户在上游故障时拿到误导性报错、免费兜底失效）和 N3（e2e 的隐性 flake 源）；N2 则是对 agent 实际使用体验影响最直接的低成本改进。依赖层（ddgs/markitdown/Exa 文档）经联网核验没有发现兼容性炸弹，编码处理链路也被证明是安全的——项目的外部假设总体扎实，问题都在自己代码的边界处理上。
