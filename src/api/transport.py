from __future__ import annotations

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP


def mount_mcp_streamable_http(app: FastAPI, *, mcp: FastMCP, path: str = "/mcp/full") -> None:
    app.mount(path, mcp.streamable_http_app())
