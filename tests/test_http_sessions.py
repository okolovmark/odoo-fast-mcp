"""Idle MCP sessions end on their own instead of piling up until a restart."""

import math

from fastmcp.server.http import FastMCPStreamableHTTPSessionManager

from odoo_fast_mcp.server import mcp


def test_idle_sessions_expire():
    # FastMCP passes no idle timeout, so the SDK default decides. Up to mcp 1.29
    # that default was None: sessions a client never deleted stayed in memory
    # for the life of the process (2245 in 17 days on the connector host).
    manager = FastMCPStreamableHTTPSessionManager(app=mcp._mcp_server)
    timeout = manager.session_idle_timeout
    assert timeout is not None
    assert math.isfinite(timeout)
    assert timeout > 0
