"""Tool router for forwarding calls to downstream MCP servers.

This module provides the ToolRouter class which handles routing tool calls
from the gateway to downstream MCP servers using various transport protocols
(HTTP, STDIO, SSE).

Usage:
    router = ToolRouter(timeout=30.0, gateway_auth_mode="auto")
    result = await router.call_tool(
        server_name="my-server",
        server_url="http://localhost:8080/mcp",
        tool_name="my_tool",
        arguments={"arg1": "value1"},
        transport="http",
    )

The router supports:
- HTTP streamable transport for HTTP-based MCP servers
- STDIO transport for subprocess-based MCP servers
- SSE transport for server-sent events based MCP servers
- Auth header forwarding based on gateway configuration
- Schema caching for performance optimization
"""

import logging
from typing import Optional, Dict, Any, List, Literal
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.sse import sse_client
import httpx
import asyncio
from cachetools import TTLCache

logger = logging.getLogger(__name__)


class ToolCallError(Exception):
    """Raised when a tool call fails."""
    pass


class ToolRouter:
    """Routes tool calls to downstream MCP servers."""
    
    def __init__(
        self,
        timeout: float = 30.0,
        cache_ttl: int = 300,
        gateway_auth_mode: Literal["auto", "static", "forward"] = "auto",
        gateway_transport: Literal["stdio", "sse", "http", "streamable-http"] = "stdio",
    ):
        """Initialize the tool router.
        
        Args:
            timeout: Default timeout for tool calls in seconds
            cache_ttl: Time-to-live for cached schemas in seconds (default: 5 minutes)
            gateway_auth_mode: Auth mode for the gateway (auto, static, forward)
            gateway_transport: Transport mode for the gateway (stdio, sse, http, streamable-http)
        """
        self._timeout = timeout
        self._gateway_auth_mode = gateway_auth_mode
        self._gateway_transport = gateway_transport
        # Cache for tool schemas: maps (server_name, tool_name) -> schema
        # TTL of 5 minutes, max 1000 entries
        self._schema_cache: TTLCache = TTLCache(maxsize=1000, ttl=cache_ttl)
    
    def cache_schema(self, server_name: str, tool_name: str, schema: Dict[str, Any]) -> None:
        """Cache a tool schema for later use.
        
        Args:
            server_name: Name of the server
            tool_name: Name of the tool
            schema: Tool schema to cache
        """
        key = f"{server_name}__{tool_name}"
        self._schema_cache[key] = schema
        logger.debug(f"Cached schema for {key}")
    
    def get_cached_schema(self, server_name: str, tool_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve a cached tool schema.
        
        Args:
            server_name: Name of the server
            tool_name: Name of the tool
            
        Returns:
            Cached schema if available, None otherwise
        """
        key = f"{server_name}__{tool_name}"
        schema = self._schema_cache.get(key)
        if schema:
            logger.debug(f"Cache hit for schema {key}")
        return schema
    
    def clear_cache(self) -> None:
        """Clear the schema cache."""
        self._schema_cache.clear()
        logger.debug("Schema cache cleared")
    
    def _should_forward_auth(self, server_transport: str) -> bool:
        """Determine if auth headers should be forwarded based on gateway auth mode.
        
        Args:
            server_transport: Transport type of the downstream server
            
        Returns:
            True if auth should be forwarded, False if static auth should be used
        """
        if self._gateway_auth_mode == "static":
            return False
        elif self._gateway_auth_mode == "forward":
            return True
        else:  # "auto"
            # If gateway is running in HTTP mode, forward auth
            # If gateway is running in STDIO/SSE mode, use static auth
            return self._gateway_transport in ("http", "streamable-http")
    
    def _get_effective_auth_headers(
        self,
        server_auth_headers: Optional[Dict[str, str]],
        client_auth_header: Optional[str],
        server_transport: str,
    ) -> Optional[Dict[str, str]]:
        """Get effective auth headers based on gateway auth mode.
        
        Args:
            server_auth_headers: Auth headers configured when registering the server
            client_auth_header: Auth header from the incoming client request
            server_transport: Transport type of the downstream server
            
        Returns:
            Effective auth headers to use
        """
        should_forward = self._should_forward_auth(server_transport)
        
        if should_forward and client_auth_header:
            # Forward client auth header
            return {"Authorization": client_auth_header}
        elif server_auth_headers:
            # Use static server auth headers
            return server_auth_headers
        else:
            return None
    
    async def call_tool(
        self,
        server_name: str,
        server_url: str,
        tool_name: str,
        arguments: Dict[str, Any],
        transport: Literal["http", "stdio", "sse"] = "http",
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        auth_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Call a tool on a downstream MCP server.
        
        Args:
            server_name: Name of the downstream server
            server_url: URL or command of the downstream server
            tool_name: Name of the tool to call
            arguments: Tool arguments
            transport: Transport type ('http', 'stdio', or 'sse')
            command: Command for stdio transport
            args: Arguments for stdio transport
            env: Environment variables for stdio transport
            auth_headers: Optional authentication headers (from server registration)
            client_auth_header: Optional authentication header from client request
            
        Returns:
            Raw tool call result from remote server
        """
        # Determine effective auth headers based on gateway auth mode
        effective_auth = self._get_effective_auth_headers(
            server_auth_headers=auth_headers,
            client_auth_header=None,  # Will be passed from the tool call
            server_transport=transport,
        )
        
        if transport == "http":
            return await self._call_tool_http(
                server_name=server_name,
                server_url=server_url,
                tool_name=tool_name,
                arguments=arguments,
                auth_headers=effective_auth,
            )
        elif transport == "stdio":
            stdio_command = command or server_url
            return await self._call_tool_stdio(
                server_name=server_name,
                command=stdio_command,
                tool_name=tool_name,
                arguments=arguments,
                args=args,
                env=env,
            )
        elif transport == "sse":
            return await self._call_tool_sse(
                server_name=server_name,
                server_url=server_url,
                tool_name=tool_name,
                arguments=arguments,
                auth_headers=effective_auth,
            )
        else:
            raise ToolCallError(f"Unsupported transport '{transport}' for server '{server_name}'")
    
    async def _execute_tool_call(
        self,
        session: ClientSession,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        """Execute a tool call on an MCP session.
        
        Args:
            session: Initialized MCP ClientSession
            tool_name: Name of the tool to call
            arguments: Tool arguments
            
        Returns:
            Tool call result
        """
        await session.initialize()
        result = await session.call_tool(tool_name, arguments)
        return self._process_tool_result(result)
    
    async def _call_tool_http(
        self,
        server_name: str,
        server_url: str,
        tool_name: str,
        arguments: Dict[str, Any],
        auth_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Call a tool using HTTP transport."""
        if not (server_url.startswith("http://") or server_url.startswith("https://")):
            raise ToolCallError(f"Invalid HTTP URL for server '{server_name}': {server_url}")
        
        logger.info(f"Calling tool '{tool_name}' on server '{server_name}' at {server_url}")
        
        headers = auth_headers or {}
        async with httpx.AsyncClient(headers=headers, timeout=self._timeout) as http_client:
            async with asyncio.timeout(self._timeout):
                async with streamable_http_client(server_url, http_client=http_client) as (read, write, _get_session_id):
                    async with ClientSession(read, write) as session:
                        return await self._execute_tool_call(session, tool_name, arguments)
    
    async def _call_tool_stdio(
        self,
        server_name: str,
        command: str,
        tool_name: str,
        arguments: Dict[str, Any],
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Call a tool using stdio transport."""
        logger.info(f"Calling tool '{tool_name}' on server '{server_name}' via stdio")
        
        stdio_params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env or {},
        )
        
        async with asyncio.timeout(self._timeout):
            async with stdio_client(stdio_params) as (read, write):
                async with ClientSession(read, write) as session:
                    return await self._execute_tool_call(session, tool_name, arguments)
    
    async def _call_tool_sse(
        self,
        server_name: str,
        server_url: str,
        tool_name: str,
        arguments: Dict[str, Any],
        auth_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Call a tool using SSE transport."""
        logger.info(f"Calling tool '{tool_name}' on server '{server_name}' via SSE at {server_url}")
        
        headers = auth_headers or {}
        
        async with asyncio.timeout(self._timeout):
            async with sse_client(server_url, headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    return await self._execute_tool_call(session, tool_name, arguments)
    
    def _process_tool_result(self, result: Any) -> Any:
        """Process the result from a tool call and return raw response."""
        return result
    
    async def call_tool_with_server_info(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        registry: Any,  # ServerRegistry
    ) -> Any:
        """Call a tool using server info from the registry.
        
        Args:
            server_name: Name of the downstream server
            tool_name: Name of the tool to call
            arguments: Tool arguments
            registry: Server registry to look up server info
            
        Returns:
            Raw tool call result from remote server
        """
        # Get server info
        server_info = await registry.get(server_name)
        if not server_info:
            raise ToolCallError(f"Server '{server_name}' not found")
        
        # Get auth config
        auth_config = await registry.get_auth_config(server_name)
        auth_headers = auth_config.headers if auth_config else None
        
        # Call the tool
        return await self.call_tool(
            server_name=server_name,
            server_url=server_info.url,
            tool_name=tool_name,
            arguments=arguments,
            transport=server_info.transport,
            command=server_info.command,
            args=server_info.args,
            env=server_info.env,
            auth_headers=auth_headers,
        )
