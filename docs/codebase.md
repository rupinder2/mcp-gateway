# MCP Gateway Codebase Documentation

## Project Overview

The MCP Gateway is a FastMCP-based server that aggregates tools from multiple downstream MCP servers, providing a unified interface with advanced search capabilities. It implements deferred tool loading compatible with Claude's Tool Search Tool protocol.

## Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP Gateway Server                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Registry   │  │    Search    │  │   Router     │      │
│  │              │  │   Service    │  │              │      │
│  │ - Server mgmt│  │ - BM25       │  │ - Call tools │      │
│  │ - Metadata   │  │ - Regex      │  │ - Schema     │      │
│  │ - Loading    │  │ - Indexing   │  │   cache      │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
         │                     │                     │
         ▼                     ▼                     ▼
┌──────────────┐      ┌─────────────────┐   ┌──────────────┐
│   Storage    │      │  Downstream     │   │  FastMCP     │
│  (Memory/    │      │  MCP Servers    │   │  Server      │
│   Redis)     │      │                 │   │              │
└──────────────┘      └─────────────────┘   └──────────────┘
```

### Key Features

#### 1. Deferred Tool Loading (Change 1-6)

The gateway now supports deferred tool loading, compatible with Claude's Tool Search Tool protocol:

- **Tool Metadata Storage**: Tools are stored as metadata without being registered as live FastMCP tools
- **Lazy Loading**: Tools are only activated when discovered via search
- **Loading Modes**: Servers can be registered with `loading_mode="eager"` (default) or `loading_mode="deferred"`
- **Dynamic Activation**: When search returns tools, they're automatically registered as callable tools

**Storage Keys**:
- `gateway:servers` - Server registrations
- `gateway:server:{name}:tools` - Full tool definitions
- `gateway:tool_meta:{server}__{tool}` - Tool metadata for search indexing

#### 2. Enhanced Search (Change 2)

The search service indexes all four metadata fields:
- Tool name
- Tool description  
- Argument names
- Argument descriptions

**Search Methods**:
- `tool_search_regex`: Pattern-based matching with regex
- `tool_search_bm25`: Natural language relevance ranking

#### 3. Claude-Compatible Response Format (Change 3)

Search results return tool_reference blocks compatible with Claude's API:

```json
{
  "success": true,
  "tool_references": [
    {
      "type": "tool_reference",
      "tool_name": "server__tool"
    }
  ],
  "tools": [
    {
      "type": "tool_reference",
      "tool_name": "server__tool",
      "description": "...",
      "input_schema": {...}
    }
  ],
  "total_matches": 1,
  "query": "search query"
}
```

#### 4. Error Code Alignment (Change 5)

Error responses include structured error codes:
- `invalid_pattern`: Malformed regex
- `pattern_too_long`: Query > 200 characters
- `unavailable`: Search service error
- `too_many_requests`: Rate limit exceeded

#### 5. Schema Caching (Change 8)

Tool schemas are cached with TTL to avoid redundant downstream calls:
- Cache key: `{server_name}__{tool_name}`
- Default TTL: 5 minutes
- Max entries: 1000

## Module Reference

### `models.py`

New models added for deferred loading:

```python
class ToolReferenceBlock(BaseModel):
    """Claude-compatible tool reference."""
    type: Literal["tool_reference"] = "tool_reference"
    tool_name: str

class ToolSearchResultEntry(BaseModel):
    """Full tool metadata for non-Claude clients."""
    type: Literal["tool_reference"] = "tool_reference"
    tool_name: str
    description: str
    input_schema: Dict[str, Any]

class ToolSearchResponse(BaseModel):
    """Unified search response format."""
    tool_references: List[ToolReferenceBlock]
    tools: List[ToolSearchResultEntry]
    total_matches: int
    query: str

class ToolSearchErrorCode(str, Enum):
    """Claude-aligned error codes."""
    TOO_MANY_REQUESTS = "too_many_requests"
    INVALID_PATTERN = "invalid_pattern"
    PATTERN_TOO_LONG = "pattern_too_long"
    UNAVAILABLE = "unavailable"

# Updated ServerRegistration
class ServerRegistration(BaseModel):
    # ... existing fields ...
    loading_mode: Literal["eager", "deferred"] = "eager"
```

### `server/registry.py`

New methods for metadata management:

```python
async def store_tool_metadata(
    self,
    server_name: str,
    tool_name: str,
    tool_data: Dict[str, Any],
) -> None

async def get_tool_metadata(
    self,
    namespaced_name: str,
) -> Optional[Dict[str, Any]]

async def get_all_tool_metadata(self) -> List[Dict[str, Any]]

async def remove_tool_metadata(self, server_name: str) -> None
```

### `tools/search.py`

Enhanced indexing with four-field support:

```python
def _build_search_document(self, tool_meta: Dict[str, Any]) -> str:
    """Build searchable text from all metadata fields."""
    # Concatenates: name, description, arg names, arg descriptions

def index_tool_metadata(self, tool_meta: Dict[str, Any]) -> None:
    """Index from stored metadata (for rebuilding index)."""

def index_all_metadata(self, metadata_list: List[Dict[str, Any]]) -> None:
    """Bulk index from metadata list."""
```

### `tools/router.py`

Added schema caching:

```python
class ToolRouter:
    def __init__(self, timeout: float = 30.0, cache_ttl: int = 300):
        self._schema_cache: TTLCache = TTLCache(maxsize=1000, ttl=cache_ttl)
    
    def cache_schema(self, server_name: str, tool_name: str, schema: Dict) -> None
    def get_cached_schema(self, server_name: str, tool_name: str) -> Optional[Dict]
```

### `mcp_server.py`

Key changes for deferred loading:

```python
class MCPGatewayServer:
    def __init__(self, ...):
        self._active_tools: set[str] = set()  # Track activated tools
    
    async def _activate_tools_from_refs(self, tool_refs: List[Any]) -> None:
        """Activate deferred tools after search discovery."""
        # Idempotent registration of tools as live FastMCP tools
```

## Tool Registration Flow

### Eager Loading (Default)

1. Register server with `loading_mode="eager"`
2. Discover tools from downstream server
3. Store full tool definitions
4. Store tool metadata
5. **Immediately register as live FastMCP tools**
6. Index for search

### Deferred Loading

1. Register server with `loading_mode="deferred"`
2. Discover tools from downstream server
3. Store full tool definitions
4. Store tool metadata
5. **Index for search only** (not registered as live tools)
6. Search returns tool_reference blocks
7. User calls discovered tool
8. **Activate tool**: Register as live FastMCP tool
9. Tool is now callable

## Search Flow

1. User calls `tool_search_regex` or `tool_search_bm25`
2. Validate query (max 200 chars for regex)
3. Clamp `max_results` to 1-10 (default 5)
4. Search indexes (all four fields)
5. Return top N results
6. **Activate deferred tools** if not already active
7. Return tool_reference format

## API Changes

### Tool Search Parameters

**Before:**
```python
async def tool_search_regex(query: str, limit: int = 5)
async def tool_search_bm25(query: str, limit: int = 5)
```

**After:**
```python
async def tool_search_regex(query: str, max_results: int = 5)
async def tool_search_bm25(query: str, max_results: int = 5)
```

**Validation:**
- `max_results` clamped to 1-10
- Regex patterns max 200 characters
- Returns error codes for invalid patterns 

### Server Registration

**Before:**
```python
async def register_server(
    name: str,
    url: str,
    connection_mode: Literal["stateful", "stateless"] = "stateless",
    # ... auth params ...
)
```

**After:**
```python
async def register_server(
    name: str,
    url: str,
    connection_mode: Literal["stateful", "stateless"] = "stateless",
    loading_mode: Literal["eager", "deferred"] = "eager",  # NEW
    # ... auth params ...
)
```

## Environment Variables

New environment variables for deferred loading:

```bash
# Deferred loading mode (eager = register all tools immediately, deferred = lazy loading)
DEFAULT_LOADING_MODE=eager

# Search defaults
SEARCH_MAX_RESULTS=5
SEARCH_REGEX_MAX_LENGTH=200

# Schema cache
SCHEMA_CACHE_TTL=300  # seconds
SCHEMA_CACHE_MAXSIZE=1000
```

## Testing

### Key Test Cases

1. **Deferred Loading**
   - Register server with `loading_mode="deferred"`
   - Verify tools are NOT callable before search
   - Search for tool
   - Verify tool IS callable after search
   - Verify idempotent activation (search twice)

2. **Search Quality**
   - Search by argument name finds correct tool
   - Search by argument description finds correct tool
   - Search by tool name works
   - Search by description works

3. **Error Handling**
   - Invalid regex returns `invalid_pattern` error code
   - Pattern > 200 chars returns `pattern_too_long` error code
   - Malformed tool name in results doesn't crash

4. **Limits**
   - Default max_results = 5
   - max_results > 10 clamped to 10
   - max_results < 1 clamped to 1

## Migration Guide

### For Existing Installations

1. **No breaking changes**: Default `loading_mode="eager"` maintains backward compatibility
2. **New storage**: Tool metadata will be stored automatically on next server registration
3. **Search improvements**: Immediate benefit without code changes

### To Enable Deferred Loading

1. Register servers with `loading_mode="deferred"`:
   ```python
   await register_server(
       name="my-server",
       url="http://localhost:8080",
       loading_mode="deferred"
   )
   ```

2. Use search to discover tools:
   ```python
   result = await tool_search_bm25("find user data")
   # Returns tool_reference blocks
   ```

3. Call discovered tools normally - they'll be auto-activated

## Performance Considerations

- **Deferred loading**: Reduces initial context size by only loading tools on demand
- **Schema caching**: Avoids redundant metadata fetches (5 min TTL)
- **Search indexing**: O(1) lookup for indexed tools
- **Result limits**: Enforced at search level to minimize data transfer

## Future Enhancements

- **Hot tool auto-promotion**: Track usage and auto-promote frequently used tools
- **Resource-based hints**: MCP resource for system prompt hints
- **Session-aware caching**: Per-session schema caching
- **Analytics**: Tool usage analytics for optimization

## References

- [Claude Tool Search Tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [FastMCP Documentation](https://gofastmcp.com)
- [MCP Specification](https://modelcontextprotocol.io)
