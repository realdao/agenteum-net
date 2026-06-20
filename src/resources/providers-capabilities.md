# Provider Capabilities

Search providers:

- Tavily: enabled only when `TAVILY_API_KEY` is configured; first paid search provider.
- Exa: enabled only when `EXA_API_KEY` is configured; fallback paid search provider.
- DuckDuckGo: no API key, always available free fallback provider through `ddgs`.

Search provider names for `parallel_search.providers`: `tavily`, `exa`, and `duckduckgo`.

Fetch providers:

- HTTP: first provider for normal HTML pages, converts HTML to Markdown with MarkItDown.
- Jina: direct provider for x.com/twitter.com and fallback provider for blocked or empty HTTP fetches.

Optional environment variables:

- `TAVILY_API_KEY`: enables Tavily.
- `EXA_API_KEY`: enables Exa.
- `JINA_API_KEY`: enables Jina Reader fallback and x.com/twitter.com direct fetches.

Tavily and Exa are enabled only when their API keys are configured. DuckDuckGo remains available without an API key.
