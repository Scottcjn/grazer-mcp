# grazer-mcp

**Multi-platform content discovery for AI agents, over the [Model Context Protocol](https://modelcontextprotocol.io) (MCP).**

Grazer lets an agent *graze* worthy content across platforms — starting with
[BoTTube](https://bottube.ai) and an extensible set of sources — returning a
normalized result shape regardless of backend.

Part of the [Elyan Labs](https://elyanlabs.ai) agent ecosystem (RustChain, BoTTube,
Beacon). Sibling of [`rustchain-mcp`](https://github.com/Scottcjn/rustchain-mcp).

## Tools

| Tool | What it does |
|------|--------------|
| `graze_platforms()` | List supported platforms and their status |
| `graze_trending(platform, limit)` | Trending content on a platform |
| `graze_discover(query, platform, page, sort, category, min_views)` | Search / discover worthy content (paged, filterable) |
| `graze_feed(platform, limit, ranked)` | Discovery feed — popularity ranker (with explanation) or newest |

Every tool returns a **stable contract**: `{"ok": true, ...}` on success, or a
predictable `{"ok": false, "error": {code, message, retryable, source, details}}`
on failure — never a silent empty result, so clients treat upstream failures as
verification failures, not zero values.

## Install

Install straight from GitHub:

```bash
pip install git+https://github.com/Scottcjn/grazer-mcp.git
```

> PyPI publication is pending, so `pip install grazer-mcp` does not work yet. The GitHub install above is the supported path for now.

## Quick start (Claude Desktop)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "grazer": { "command": "grazer-mcp" }
  }
}
```

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `GRAZER_API_URL` | `https://bottube.ai` | Discovery backend base URL |
| `GRAZER_TIMEOUT` | `20` | Per-request timeout (seconds) |

## Platforms

| Platform | Status |
|----------|--------|
| `bottube` | live |

More sources resolve through the same backend as Grazer grows. Status in
`graze_platforms()` is kept honest — only `live` platforms are backed today.

**Live BoTTube endpoints** (verified): `trending` → `/api/trending`, `discover` → `/api/search`, `feed` → `/api/v2/feed` (ranked) / `/api/feed` (newest). Video objects are normalized to `{id, title, agent, views, likes, category, url, thumbnail, duration_sec, created_at, tags}`.

## Development

```bash
python3 -m pytest -q          # or: python3 tests/test_client.py
```

The discovery logic lives in `grazer_mcp/client.py` (pure, network-mocked tests,
no MCP dependency); `grazer_mcp/server.py` is a thin MCP wrapper over it.

## License

MIT — see [LICENSE](LICENSE). © 2026 Scott Boudreaux / Elyan Labs LLC.
