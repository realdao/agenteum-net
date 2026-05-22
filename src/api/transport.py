from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette


def mount_mcp_streamable_http(mcp: FastMCP) -> Starlette:
    return mcp.streamable_http_app()
