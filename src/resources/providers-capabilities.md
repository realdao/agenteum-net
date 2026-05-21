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
