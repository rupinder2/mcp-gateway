# MCP Orchestration Gateway

[![PyPI Version](https://img.shields.io/pypi/v/mcp-orchestration-gateway.svg)](https://pypi.org/project/mcp-orchestration-gateway/)
[![Python Version](https://img.shields.io/pypi/pyversions/mcp-orchestration-gateway)](https://pypi.org/project/mcp-orchestration-gateway/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/rupinder2/mcp-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/rupinder2/mcp-gateway/actions)
[![Contributions Welcome](https://img.shields.io/badge/Contributions-Welcome-blue.svg)](CONTRIBUTING.md)

A central hub that connects to multiple downstream MCP servers, aggregates their tools, and provides unified access with powerful tool search capabilities.

> Built around **deferred tool loading** — search across all your servers without blowing Claude's context window.

## Features

- **Config-based Server Registration**: Add downstream MCP servers via JSON config file
- **Tool Namespacing**: Automatic `server_name__tool_name` format
- **Tool Search**: Unified BM25/regex search with deferred loading support
- **Flexible Authentication**: Static saved headers or token forwarding
- **Multiple Transports**: stdio or HTTP
- **Tool Definition Caching**: Cached definitions, raw result passthrough
- **Storage Backends**: In-memory (development) or Redis (production)

## Quick Start

### Installation

```bash
pip install -e .
```

### Running the MCP Server

First, activate the virtual environment:

```bash
source .venv/bin/activate
```

Then run the server:

```bash
# Run as stdio MCP server (for Claude Desktop, Cursor, etc.)
mcp-orchestration-gateway

# Or run with Python directly
python -m mcp_gateway.main
```

**HTTP Transport:**

```bash
GATEWAY_TRANSPORT=http GATEWAY_PORT=8080 python -m mcp_gateway.main
```

This starts the server on `http://localhost:8080/mcp` with CORS enabled.

### Configuring Servers

Add downstream MCP servers in `server_config.json`:

```json
{
  "servers": [
    {
      "name": "my-server",
      "url": "http://localhost:8080/mcp",
      "transport": "http",
      "auth_type": "static",
      "auth_headers": {
        "Authorization": "Bearer my-token"
      }
    },
    {
      "name": "my-stdio-server",
      "url": "server.py",
      "transport": "stdio",
      "command": "uv",
      "args": ["run", "python", "server.py"]
    }
  ]
}
```

### Searching for Tools

The gateway provides unified tool search (BM25 by default, regex optional):

```python
# BM25 search (default - natural language)
results = await mcp_client.call_tool("tool_search", {
    "query": "get weather information",
    "max_results": 3
})

# Regex search (set use_regex=true)
results = await mcp_client.call_tool("tool_search", {
    "query": "weather|forecast",
    "use_regex": true,
    "max_results": 3
})
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              MCP Orchestration Gateway               │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │              FastMCP Server                   │   │
│  │  ┌─────────────┐  ┌──────────────────┐   │   │
│  │  │ tool_search │  │ call_remote_tool  │   │   │
│  │  └─────────────┘  └──────────────────┘   │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐      │
│  │  Server  │  │   Tool   │  │   Storage    │      │
│  │ Registry │  │  Search  │  │(Memory/Redis)│      │
│  └──────────┘  └──────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────┘
                           │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   ┌─────────┐        ┌─────────┐        ┌─────────┐
   │ MCP Svr │        │ MCP Svr │        │ MCP Svr │
   │   #1    │        │   #2    │        │   #N    │
   └─────────┘        └─────────┘        └─────────┘
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_BACKEND` | `memory` | Storage backend (`memory` or `redis`) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `MCP_GATEWAY_TOOL_CACHE_TTL` | `300` | Tool schema cache TTL in seconds |
| `MCP_GATEWAY_DEFAULT_CONNECTION_MODE` | `stateless` | Default connection mode |
| `MCP_GATEWAY_CONNECTION_TIMEOUT` | `30.0` | Connection timeout in seconds |
| `MCP_GATEWAY_MAX_RETRIES` | `3` | Maximum retry attempts |
| `GATEWAY_TRANSPORT` | `stdio` | MCP transport (`stdio` or `http`) |
| `GATEWAY_PORT` | `8080` | Port for HTTP transport |
| `GATEWAY_HOST` | `0.0.0.0` | Host for HTTP transport |
| `GATEWAY_LOG_LEVEL` | `INFO` | Logging level |
| `SERVER_CONFIG_PATH` | `server_config.json` | Path to server configuration file |

### Claude Desktop Integration

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mcp-orchestration-gateway": {
      "command": "mcp-orchestration-gateway",
      "env": {
        "STORAGE_BACKEND": "memory",
        "GATEWAY_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

## MCP Tools

### tool_search

Search for tools using BM25 relevance ranking or regex pattern matching.

```python
@mcp.tool()
async def tool_search(
    query: str,
    max_results: int = 3,
    use_regex: bool = False,
) -> dict:
    """Search for tools using BM25 or regex.
    
    By default uses BM25 natural language search. Set use_regex=True
    to search using Python regex patterns instead.
    """
```

### discover_tools

Discover tools from a registered downstream server.

```python
@mcp.tool()
async def discover_tools(
    server_name: str,
) -> dict:
    """Discover tools from a registered server and index them for search.
    
    Returns the list of discovered tools with their schemas.
    """
```

### call_remote_tool

Call a tool directly on a downstream MCP server.

```python
@mcp.tool()
async def call_remote_tool(
    tool_name: str,
    arguments: Optional[dict] = None,
    auth_header: Optional[str] = None,
) -> Any:
    """Call a tool on a downstream server.
    
    Args:
        tool_name: Namespaced tool name (server_name__tool_name)
        arguments: Tool arguments
        auth_header: Optional auth header to override server's configured auth
    """
```

## Tool Search Results

The search tools return results in the format expected by Claude's tool search system:

```json
{
  "success": true,
  "tool_references": [
    {
      "type": "tool_reference",
      "tool_name": "server_name__tool_name"
    }
  ],
  "total_matches": 5,
  "query": "weather"
}
```

## Testing

Run the test suite:

```bash
uv run pytest
```

Run with coverage:

```bash
uv run pytest --cov=mcp_gateway
```

## Project Structure

```
mcp-gateway/
├── src/mcp_gateway/
│   ├── __init__.py
│   ├── main.py              # Entry point
│   ├── models.py            # Pydantic models
│   ├── mcp_server.py        # FastMCP server
│   ├── config_loader.py     # Config file loader
│   ├── server/
│   │   └── registry.py      # Server registry
│   ├── tools/
│   │   ├── router.py       # Tool router
│   │   └── search.py       # Tool search service
│   └── storage/
│       ├── base.py          # Storage interface
│       ├── memory.py        # In-memory backend
│       └── redis.py         # Redis backend
├── tests/
│   ├── test_registry.py
│   ├── test_search.py
│   ├── test_storage.py
│   ├── test_models.py
│   └── test_integration.py
├── server_config.json       # Pre-configured downstream servers
├── pyproject.toml
├── README.md
└── .env                    # Environment variables (not committed)
```

## License

MIT License

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
