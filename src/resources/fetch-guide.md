# agenteum_fetch

Use `agenteum_fetch` to read known HTTP or HTTPS URLs as Markdown.

Parameters:

- `urls`: 1 to 10 URLs.

The tool returns one result item per input URL. Individual failures are reported in the matching result item and do not fail the whole batch.

`x.com` and `twitter.com` URLs go directly to Jina. Other URLs use HTTP fetch first and fall back to Jina when the HTTP result appears blocked, empty, timed out, or otherwise unavailable.
