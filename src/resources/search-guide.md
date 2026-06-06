# search

Use `search` to discover relevant web pages for a query.

Parameters:

- `query`: required search query.
- `max_result`: result count from 1 to 20, default 10.
- `time_range`: best-effort value among `day`, `week`, `month`, `year`, `d`, `w`, `m`, and `y`.
- `topic`: best-effort topic hint. Tavily supports `general`, `news`, and `finance`.

Provider fallback order is Tavily, then Exa, then DuckDuckGo.
