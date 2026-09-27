#!/usr/bin/env python3
"""
grazer-mcp — Multi-platform content discovery for AI agents, over MCP.

Grazer lets an agent "graze" worthy content across platforms (BoTTube and an
extensible set of sources), returning a normalized shape regardless of backend.

Tools:
  graze_platforms()                       list supported platforms + status
  graze_trending(platform, limit)         trending content on a platform
  graze_discover(query, platform, limit)  search/discover worthy content
  graze_feed(platforms, limit)            aggregated cross-platform feed

Config (env): GRAZER_API_URL (default https://bottube.ai), GRAZER_TIMEOUT (20).

Every tool returns {"ok": true, ...} or a predictable {"ok": false, "error": {...}}
object — never a silent empty result.
"""
from __future__ import annotations

try:  # mcp >= 2.0.0 removed mcp.server.fastmcp; FastMCP was renamed
    # MCPServer and moved to mcp.server.mcpserver. Same .tool()/.run() API.
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from .client import GrazerClient

mcp = FastMCP("grazer-mcp")
_client = GrazerClient()


@mcp.tool()
def graze_platforms() -> dict:
    """List the content platforms grazer can discover across, with status."""
    return _client.platforms()


@mcp.tool()
def graze_trending(platform: str = "bottube", limit: int = 10) -> dict:
    """Return trending content on a platform. platform: see graze_platforms(); limit 1-50."""
    return _client.trending(platform, limit)


@mcp.tool()
def graze_discover(query: str, platform: str = "bottube", page: int = 1,
                   sort: str | None = None, category: str | None = None,
                   min_views: int | None = None) -> dict:
    """Search/discover worthy content matching `query`.

    platform: see graze_platforms(). page: pagination (1+). Optional filters:
    sort (e.g. "views", "recent"), category, min_views. Returns normalized items
    plus total/pages.
    """
    return _client.discover(query, platform, page, sort, category, min_views)


@mcp.tool()
def graze_feed(platform: str = "bottube", limit: int = 10, ranked: bool = True) -> dict:
    """Discovery feed. ranked=True -> popularity ranker (with explanation); ranked=False -> newest. limit 1-50."""
    return _client.feed(platform, limit, ranked)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
