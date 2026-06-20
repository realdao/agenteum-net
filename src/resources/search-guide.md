# search

Use `search` to discover relevant web pages for a query.

Parameters:

- `query`: required search query.
- `max_result`: result count from 1 to 20, default 10.
- `time_range`: best-effort value among `day`, `week`, `month`, `year`, `d`, `w`, `m`, and `y`.
- `topic`: best-effort topic hint. Tavily supports `general`, `news`, and `finance`.

Active provider order skips unconfigured paid providers. When both paid keys are configured, fallback order is Tavily, then Exa, then DuckDuckGo. With no paid keys, DuckDuckGo remains available without an API key.

# parallel_search

Use `parallel_search` to query multiple search providers at the same time, merge results, and deduplicate by URL.

Parameters:

- `query`: required search query.
- `max_result`: per-provider result count from 1 to 20, default 10.
- `time_range`: best-effort value among `day`, `week`, `month`, `year`, `d`, `w`, `m`, and `y`.
- `topic`: best-effort topic hint. Tavily supports `general`, `news`, and `finance`.
- `providers`: optional provider names such as `["tavily", "exa"]`. Empty or `None` uses all providers. A single provider is allowed.

Results are merged in active provider order. Unconfigured paid providers are skipped; duplicate provider names are ignored after their first occurrence. Duplicate URLs keep the first result. If some providers fail, successful results are returned with provider errors in `errors`. If all selected providers fail, the tool raises a provider error.
