# Agenteum Net

Agenteum Net is an HTTP-only MCP server that exposes web search and web fetch tools for local agent clients.

## v1.0 Tools

- `search(query, max_result=10, time_range=None, topic=None)`
- `parallel_search(query, max_result=10, time_range=None, topic=None, providers=None)`
- `fetch(urls)`

## Local Run

```bash
uv sync
uv run agenteum-net
```

The MCP endpoint is available at:

```text
http://127.0.0.1:8765/mcp/full
```

## WSL Access

The server binds to `127.0.0.1` by default. For WSL clients that need host-visible binding:

```env
AGENTEUM_HOST=0.0.0.0
AGENTEUM_ALLOW_REMOTE=true
```

v1.0 has no authentication. Do not expose a remote bind address to an untrusted network.

## Logging

Set `AGENTEUM_LOG_LEVEL=DEBUG` in `.env` to include tool result payloads. Tool calls and parameters are logged at `INFO`.

## Development Checks

```bash
uv run pytest
uv run ruff check .
```

## Security

Agenteum Net v1.0 has no authentication. The default host is `127.0.0.1`. Setting `AGENTEUM_HOST=0.0.0.0` requires `AGENTEUM_ALLOW_REMOTE=true` and is only intended for trusted local or WSL setups.

## Manual Provider Smoke Checks

Default automated tests do not call real Tavily, Exa, Jina, or DuckDuckGo endpoints.

After placing real keys in `.env`, start the server:

```bash
uv run agenteum-net
```

Then connect an MCP client to:

```text
http://127.0.0.1:8765/mcp/full
```

Run one search query and one fetch request manually to validate local provider credentials.
