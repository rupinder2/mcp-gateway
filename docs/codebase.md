# MCP Gateway Codebase Snapshot

> Last updated: February 2026

## Overview

MCP Orchestration Gateway is a FastMCP-based server that aggregates tools from multiple downstream MCP servers, providing unified access with BM25/regex search and deferred tool loading.

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
│  │        │                  │                │   │
│  │        ▼                  ▼                │   │
│  │  ┌──────────────────────────────────────┐  │   │
│  │  │     Deferred Tool Activation          │  │   │
│  │  │  (activates tools on search results)  │  │   │
│  │  └──────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐      │
│  │  Server  │  │   Tool   │  │   Storage    │      │
│  │ Registry │  │  Search  │  │(Memory/Redis)│      │
│  └──────────┘  └──────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────┘
```

## Module Reference

### Core

| File | Description |
|------|-------------|
| `main.py` | Entry point - creates storage, registry, search service, and runs FastMCP server |
| `mcp_server.py` | FastMCP server implementation with search/call tools and dynamic tool registration |
| `models.py` | Pydantic models for GatewayConfig, ServerRegistration, ServerInfo, AuthConfig, ToolReference |
| `config_loader.py` | Loads server configurations from JSON file |

### Server Registry (`server/registry.py`)

Manages downstream MCP server registrations:
- `register()` - Register a new server with auth config
- `get()` / `get_auth_config()` - Retrieve server info
- `store_tools()` / `get_tools()` - Tool caching
- `list_all()` - List all registered servers

### Tool Router (`tools/router.py`)

Routes tool calls to downstream servers:
- `call_tool()` - Forward tool invocations via HTTP or stdio transport
- Handles auth header priority: user-provided > server-configured > none

### Tool Search (`tools/search.py`)

BM25 and regex search across all indexed tools:
- `index_tools()` - Index tools from a server
- `search()` - BM25 (default) or regex search
- Returns `ToolReference` objects with namespaced names

### Storage Backends (`storage/`)

| Backend | File | Description |
|---------|------|-------------|
| In-memory | `memory.py` | Development, non-persistent |
| Redis | `redis.py` | Production, persistent |

## Key Patterns

### Tool Naming

All tools use namespaced format: `server_name__tool_name` (double underscore)

### Auth Header Priority

1. User-provided `auth_header` in tool call (highest)
2. Registered auth headers from server registration
3. No auth (if neither available)

### Deferred Tool Loading

1. Tools are NOT registered as FastMCP tools on startup
2. `tool_search` discovers tools and returns `tool_reference` blocks
3. `_activate_tools_from_refs()` registers found tools as live FastMCP tools
4. Subsequent calls to those tools work directly

### Structured Responses

```python
# Success
{"success": True, "data": result}

# Error
{"success": False, "error": "Human-readable message", "tool": tool_name}
```

## Configuration

Environment variables (see `main.py:create_config_from_env()`):

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_BACKEND` | `memory` | Storage backend |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `GATEWAY_TRANSPORT` | `stdio` | `stdio` or `http` |
| `GATEWAY_PORT` | `8080` | HTTP port |
| `GATEWAY_LOG_LEVEL` | `INFO` | Logging level |
| `SERVER_CONFIG_PATH` | `server_config.json` | Server config file |

## Dependencies

- `fastmcp>=2.14.0` - MCP server framework
- `mcp>=1.0.0` - MCP SDK for client connections
- `pydantic>=2.5.0` - Data validation
- `httpx>=0.26.0` - Async HTTP client
- `whoosh>=2.7.4` - BM25 search
- `redis>=5.0.0` - Optional Redis storage
- `structlog>=24.1.0` - Structured logging
