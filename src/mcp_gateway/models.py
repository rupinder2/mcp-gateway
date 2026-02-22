"""Data models for MCP Gateway."""

from datetime import datetime
from typing import Optional, Literal, Dict, Any, List
from enum import Enum
from pydantic import BaseModel, Field


TransportType = Literal["http", "stdio"]
TransportMode = Literal["stdio", "http"]
AuthType = Literal["none", "static", "forward"]
AuthMode = Literal["auto", "static", "forward"]
ConnectionMode = Literal["stateful", "stateless"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class ToolSearchErrorCode(str, Enum):
    """Error codes for tool search operations, aligned with Claude's native format."""
    TOO_MANY_REQUESTS = "too_many_requests"
    INVALID_PATTERN = "invalid_pattern"
    PATTERN_TOO_LONG = "pattern_too_long"
    UNAVAILABLE = "unavailable"


class ToolReferenceBlock(BaseModel):
    """A tool reference block compatible with Claude's tool_reference format."""
    type: Literal["tool_reference"] = "tool_reference"
    tool_name: str = Field(..., description="Namespaced tool name: server__tool")


class ToolSearchResultEntry(BaseModel):
    """Detailed tool result entry with full metadata for non-Claude clients."""
    type: Literal["tool_reference"] = "tool_reference"
    tool_name: str
    description: str
    input_schema: Dict[str, Any]


class ToolSearchResponse(BaseModel):
    """Response from tool search, compatible with Claude's tool_reference protocol."""
    tool_references: List[ToolReferenceBlock]
    tools: List[ToolSearchResultEntry]  # Full metadata for non-Claude clients
    total_matches: int
    query: str


class AuthConfig(BaseModel):
    """Authentication configuration for downstream servers."""
    type: AuthType = "none"
    headers: Optional[Dict[str, str]] = None
    header_name: Optional[str] = "Authorization"
    header_prefix: Optional[str] = "Bearer"


class ServerRegistration(BaseModel):
    """Request to register a new MCP server."""
    name: str = Field(..., description="Unique server name", min_length=1)
    url: str = Field(..., description="MCP server URL or command for stdio")
    transport: TransportType = "http"
    command: Optional[str] = Field(None, description="Command to run for stdio transport (e.g., 'npx', 'python')")
    args: Optional[List[str]] = Field(None, description="Arguments for stdio transport command")
    env: Optional[Dict[str, str]] = Field(None, description="Environment variables for stdio transport")
    connection_mode: ConnectionMode = "stateless"
    auth: AuthConfig = Field(default_factory=lambda: AuthConfig(type="none"))
    auto_discover: bool = True
    loading_mode: Literal["eager", "deferred"] = "eager"


class ServerInfo(BaseModel):
    """Information about a registered server."""
    name: str
    url: str
    transport: TransportType = "http"
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    connection_mode: ConnectionMode
    auth_type: AuthType
    status: Literal["active", "inactive", "error", "unknown"]
    registered_at: datetime
    last_health_check: Optional[datetime] = None
    tool_count: int = 0
    error_message: Optional[str] = None


class ToolReference(BaseModel):
    """Reference to a discovered tool."""
    server_name: str
    tool_name: str
    namespaced_name: str  # server_name__tool_name
    description: str
    input_schema: Dict[str, Any]
    defer_loading: bool = True


class ToolSearchRequest(BaseModel):
    """Request to search for tools."""
    query: str = Field(..., max_length=200)
    search_type: Literal["regex", "bm25"] = "bm25"
    limit: int = Field(default=5, ge=1, le=20)


class ToolSearchResult(BaseModel):
    """Result of tool search."""
    tool_references: List[ToolReference]
    total_matches: int


class ToolCallRequest(BaseModel):
    """Request to call a tool."""
    server_name: str
    tool_name: str
    arguments: Dict[str, Any]


class GatewayConfig(BaseModel):
    """Main gateway configuration."""
    storage_backend: Literal["memory", "redis"] = "memory"
    redis_url: Optional[str] = "redis://localhost:6379/0"
    
    tool_cache_ttl: int = 300
    
    default_connection_mode: ConnectionMode = "stateless"
    connection_timeout: float = 30.0
    max_retries: int = 3
    
    http_host: str = "0.0.0.0"
    http_port: int = 8000
    
    mcp_transport: TransportMode = "stdio"
    
    gateway_auth_mode: AuthMode = "auto"
    
    server_config_path: Optional[str] = "server_config.json"
    
    log_level: LogLevel = "INFO"


class ServerConfigEntry(BaseModel):
    """Entry in server_config.json for pre-configuring servers at startup."""
    name: str = Field(..., description="Unique server name", min_length=1)
    url: str = Field(..., description="MCP server URL or command for stdio")
    transport: TransportType = "http"
    command: Optional[str] = Field(None, description="Command to run for stdio transport")
    args: Optional[List[str]] = Field(None, description="Arguments for stdio transport command")
    env: Optional[Dict[str, str]] = Field(None, description="Environment variables for stdio transport")
    connection_mode: ConnectionMode = "stateless"
    auth_type: AuthType = "none"
    auth_headers: Optional[Dict[str, str]] = Field(None, description="Static auth headers")
    auth_header_name: Optional[str] = "Authorization"
    auto_discover: bool = True
    enabled: bool = Field(True, description="Whether to load this server at startup")
    expose_tools: bool = Field(
        default=False, 
        description="Whether to expose tools in tools/list (default: hidden, use call_remote_tool)"
    )


class ServerConfigFile(BaseModel):
    """Root of server_config.json"""
    version: str = "1.0"
    servers: List[ServerConfigEntry] = Field(default_factory=list)
