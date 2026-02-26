"""FastMCP server for MCP Orchestrator."""

import logging
from typing import Optional, Dict, Any, List, Literal
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client, StdioServerParameters
import httpx
import asyncio

from .storage.base import StorageBackend
from .server.registry import ServerRegistry
from .tools.search import ToolSearchService
from .tools.router import ToolRouter
from .models import (
    ServerRegistration,
    ServerInfo,
    AuthConfig,
    ToolReference,
)

logger = logging.getLogger(__name__)


class MCPOrchestratorServer:
    """FastMCP server implementation for MCP Orchestrator."""

    def __init__(
        self,
        storage: StorageBackend,
        server_registry: ServerRegistry,
        tool_search: ToolSearchService,
        auth_mode: Literal["auto", "static", "forward"] = "auto",
        transport: Literal["stdio", "http"] = "stdio",
    ):
        """Initialize the MCP Orchestrator server.

        Args:
            storage: Storage backend for persistent data
            server_registry: Server registry for managing MCP servers
            tool_search: Tool search service for regex and BM25 search
            auth_mode: Auth mode for the orchestrator (auto, static, forward)
            transport: Transport mode for the orchestrator (stdio or http)
        """
        self._storage = storage
        self._registry = server_registry
        self._tool_search = tool_search
        self._auth_mode = auth_mode
        self._transport = transport
        self._tool_router = ToolRouter(auth_mode=auth_mode, transport=transport)

        # Track which deferred tools have been activated as live FastMCP tools
        self._active_tools: set[str] = set()

        # Initialize FastMCP server
        self._mcp = FastMCP("mcp-orchestrator")
        
        # Register search tools
        self._register_search_tools()
    
    async def _discover_tools(
        self,
        name: str,
        url: str,
        transport: Literal["http", "stdio"] = "http",
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        auth_headers: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Discover tools from a downstream MCP server.
        
        Args:
            name: Server name
            url: Server URL (HTTP endpoint) or command for stdio
            transport: Transport type ('http' or 'stdio')
            command: Command to run for stdio transport
            args: Arguments for stdio transport command
            env: Environment variables for stdio transport
            auth_headers: Optional auth headers to include
            
        Returns:
            List of tool definitions
        """
        try:
            if transport == "http":
                return await self._discover_tools_http(name, url, auth_headers)
            elif transport == "stdio":
                stdio_command = command or url
                return await self._discover_tools_stdio(name, stdio_command, args, env)
            else:
                logger.warning(f"Unsupported transport '{transport}' for server '{name}'")
                return []
        except Exception as e:
            logger.error(f"Error discovering tools from '{name}': {e}")
            raise

    def _extract_tools_from_response(
        self,
        response: Any,
        server_name: str,
    ) -> List[Dict[str, Any]]:
        """Extract tool definitions from list_tools response.
        
        Args:
            response: The ListToolsResult from MCP session
            server_name: Name of the server (for logging)
            
        Returns:
            List of tool definition dicts
        """
        tools = []
        for tool in response.tools:
            tool_data = {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            tools.append(tool_data)
            logger.debug(f"Discovered tool: {tool.name}")
        
        logger.info(f"Discovered {len(tools)} tools from '{server_name}'")
        return tools

    async def _discover_tools_with_session(
        self,
        transport: str,
        server_name: str,
        url: str,
        http_client: Optional[httpx.AsyncClient] = None,
        stdio_params: Optional[StdioServerParameters] = None,
    ) -> List[Dict[str, Any]]:
        """Create session and discover tools within the same context.
        
        This ensures the session stays alive during tool discovery.
        """
        if transport == "http":
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    response = await session.list_tools()
                    return self._extract_tools_from_response(response, server_name)
        elif transport == "stdio":
            assert stdio_params is not None
            async with stdio_client(stdio_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    response = await session.list_tools()
                    return self._extract_tools_from_response(response, server_name)
        else:
            raise ValueError(f"Unsupported transport: {transport}")
    
    async def _discover_tools_http(
        self,
        name: str,
        url: str,
        auth_headers: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Discover tools from a downstream MCP server using HTTP streamable transport."""
        logger.info(f"Connecting to HTTP streamable endpoint: {url}")
        
        headers = auth_headers or {}
        
        try:
            async with httpx.AsyncClient(headers=headers, timeout=30.0) as http_client:
                async with asyncio.timeout(30):
                    return await self._discover_tools_with_session(
                        transport="http",
                        server_name=name,
                        url=url,
                        http_client=http_client,
                    )
        except asyncio.TimeoutError:
            logger.error(f"Timeout discovering tools from '{name}'")
            raise ConnectionError(f"Connection to '{name}' timed out after 30 seconds")
        except Exception as e:
            logger.error(f"Error discovering tools from '{name}': {e}")
            raise
    
    async def _discover_tools_stdio(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Discover tools from a downstream MCP server using stdio transport."""
        logger.info(f"Connecting to stdio MCP server: {command}")
        
        stdio_params = StdioServerParameters(
            command=command,
            args=args or [],
            env=env or {},
        )
        
        try:
            async with asyncio.timeout(30):
                return await self._discover_tools_with_session(
                    transport="stdio",
                    server_name=name,
                    url="",
                    stdio_params=stdio_params,
                )
        except asyncio.TimeoutError:
            logger.error(f"Timeout discovering tools from '{name}'")
            raise ConnectionError(f"Connection to '{name}' timed out after 30 seconds")
        except Exception as e:
            logger.error(f"Error discovering tools from '{name}': {e}")
            raise
    
    def _register_search_tools(self) -> None:
        """Register search tools for the orchestrator."""
        
        @self._mcp.tool()
        async def tool_search(
            query: str,
            max_results: int = 3,
            use_regex: bool = False,
        ) -> Dict[str, Any]:
            """Search for tools using BM25 relevance ranking or regex pattern matching.
            
            Searches across tool names, descriptions, and argument names/descriptions.
            By default, uses BM25 natural language search. Set use_regex=True to search
            using Python regex patterns instead.
            Returns tool_reference blocks for discovered tools with deferred loading.
            
            Args:
                query: Natural language query (BM25) or regex pattern (if use_regex=True)
                max_results: Maximum number of results (1-10, default 3)
                use_regex: If True, treat query as regex pattern; otherwise use BM25 search
            
            Returns:
                Tool search results with tool_reference blocks for discovered tools
            """
            try:
                # Validate max_results (clamp to 1-10)
                max_results = max(1, min(10, max_results))
                
                # Validate query length (max 200 chars per Claude spec)
                if len(query) > 200:
                    return {
                        "success": False,
                        "error_code": "query_too_long",
                        "error": "Query exceeds 200 character limit",
                    }
                
                # Perform search (BM25 by default, regex if requested)
                tool_refs = self._tool_search.search(query, limit=max_results, use_regex=use_regex)
                
                # Activate deferred tools if needed
                await self._activate_tools_from_refs(tool_refs)
                
                # Build tool_reference blocks (Claude-compatible format)
                tool_references = [
                    {
                        "type": "tool_reference",
                        "tool_name": ref.namespaced_name,
                    }
                    for ref in tool_refs
                ]
                
                # Build full metadata for non-Claude clients
                tools = [
                    {
                        "type": "tool_reference",
                        "tool_name": ref.namespaced_name,
                        "description": ref.description,
                        "input_schema": ref.input_schema,
                    }
                    for ref in tool_refs
                ]
                
                return {
                    "success": True,
                    "tool_references": tool_references,
                    "tools": tools,
                    "total_matches": len(tool_refs),
                    "query": query,
                    "search_type": "regex" if use_regex else "bm25",
                }
                
            except ValueError as e:
                # Invalid regex pattern
                logger.warning(f"Invalid regex pattern: {query} - {e}")
                return {
                    "success": False,
                    "error_code": "invalid_pattern",
                    "error": f"Invalid regex pattern: {str(e)}",
                }
            except Exception as e:
                logger.exception(f"Error in tool search: {e}")
                return {
                    "success": False,
                    "error_code": "unavailable",
                    "error": f"Search service error: {str(e)}",
                }
        
        @self._mcp.tool()
        async def call_remote_tool(
            tool_name: str,
            arguments: Optional[Dict[str, Any]] = None,
            auth_header: Optional[str] = None,
        ) -> Any:
            """Call a tool directly on a registered remote MCP server through the orchestrator.
            
            This tool allows direct invocation of any tool on a downstream MCP server.
            The tool name should be in the format 'server_name__tool_name' (e.g., 'context7__query-docs').
            
            Args:
                tool_name: Full tool name in format 'server_name__tool_name'
                arguments: Tool arguments as a dictionary (optional)
                auth_header: Optional auth header to use for this call (overrides registered auth)
            
            Returns:
                Raw tool call result from the remote server
            """
            if arguments is None:
                arguments = {}
            
            # Parse server name from tool name (format: server_name__tool_name)
            if "__" not in tool_name:
                raise ValueError(f"Invalid tool name format '{tool_name}'. Expected format: 'server_name__tool_name' (e.g., 'context7__query-docs')")
            
            server_name, actual_tool_name = tool_name.split("__", 1)
            
            # Get server info
            server_info = await self._registry.get(server_name)
            if not server_info:
                raise ValueError(f"Server '{server_name}' not found. Add it to server_config.json to register.")
            
            # Determine auth headers to use
            auth_headers = None
            if auth_header:
                # User provided auth header takes priority
                auth_headers = {"Authorization": auth_header}
            else:
                # Fall back to registered auth config
                auth_config = await self._registry.get_auth_config(server_name)
                if auth_config and auth_config.headers:
                    auth_headers = auth_config.headers
            
            # Call the tool through the router - returns raw response from remote server
            return await self._tool_router.call_tool(
                server_name=server_name,
                server_url=server_info.url,
                tool_name=actual_tool_name,
                arguments=arguments,
                transport=server_info.transport,
                command=server_info.command,
                args=server_info.args,
                env=server_info.env,
                auth_headers=auth_headers,
            )
    
    async def register_dynamic_tools(self) -> None:
        """Register dynamically discovered tools from downstream servers.
        
        This method discovers tools from all registered servers and creates
        proxied tools with namespaced names (server_name__tool_name).
        """
        try:
            servers = await self._registry.list_all()
            
            for server in servers:
                try:
                    tools = await self._registry.get_tools(server.name)
                    
                    for tool_data in tools:
                        tool_name = tool_data.get("name")
                        if not tool_name:
                            continue
                        
                        namespaced_name = f"{server.name}__{tool_name}"
                        
                        # Create dynamic tool function
                        self._create_dynamic_tool(server.name, tool_name, tool_data)
                        
                    # Index tools for search
                    self._tool_search.index_tools(server.name, tools)
                    
                    # Update tool count
                    await self._registry.update_tool_count(server.name, len(tools))
                    
                except Exception as e:
                    logger.error(f"Error loading tools from server '{server.name}': {e}")
                    
        except Exception as e:
            logger.exception(f"Error registering dynamic tools: {e}")
    
    def _create_dynamic_tool(
        self,
        server_name: str,
        tool_name: str,
        tool_data: Dict[str, Any],
    ) -> None:
        """Create a dynamic tool that proxies to a downstream server.
        
        Args:
            server_name: Name of the upstream server
            tool_name: Name of the tool on the upstream server
            tool_data: Tool definition data including description and input_schema
        """
        import inspect
        from typing import get_type_hints, Optional
        
        namespaced_name = f"{server_name}__{tool_name}"
        description = tool_data.get("description", "")
        input_schema = tool_data.get("input_schema", {})
        
        # Build a comprehensive description including server info and schema
        full_description = f"""{description}

This tool is proxied from '{server_name}' server via MCP Orchestrator.
Original tool name: {tool_name}

Input Schema:
{input_schema}
"""
        
        # Extract parameters from input_schema
        properties = input_schema.get("properties", {})
        required = input_schema.get("required", [])
        
        # Build function signature parameters
        sig_params = []
        for param_name, param_info in properties.items():
            param_type = param_info.get("type", "str")
            is_required = param_name in required
            
            # Map JSON schema types to Python types
            type_map = {
                "string": "str",
                "number": "float",
                "integer": "int",
                "boolean": "bool",
                "array": "list",
                "object": "dict",
            }
            py_type = type_map.get(param_type, "str")
            
            # Create default value for optional params
            if is_required:
                default = ...
            else:
                default = None
            
            # Create the parameter
            param = inspect.Parameter(
                param_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
            )
            sig_params.append(param)
        
        # Create function signature
        sig = inspect.Signature(parameters=sig_params)
        
        # Create closure to capture server_name and tool_name
        def make_tool_handler(srv_name: str, t_name: str, signature: inspect.Signature):
            async def dynamic_tool(**kwargs) -> Any:
                """Dynamic tool that routes to downstream server."""
                # Get server info and auth config
                server_info = await self._registry.get(srv_name)
                if not server_info:
                    raise ValueError(f"Server '{srv_name}' not found")
                
                auth_config = await self._registry.get_auth_config(srv_name)
                auth_headers = auth_config.headers if auth_config else None
                
                # Route the tool call - returns raw response from remote server
                return await self._tool_router.call_tool(
                    server_name=srv_name,
                    server_url=server_info.url,
                    tool_name=t_name,
                    arguments=kwargs,
                    transport=server_info.transport,
                    command=server_info.command,
                    args=server_info.args,
                    env=server_info.env,
                    auth_headers=auth_headers,
                )
            
            # Set the signature on the function
            dynamic_tool.__signature__ = signature
            return dynamic_tool
        
        # Create the tool handler with captured values
        dynamic_tool = make_tool_handler(server_name, tool_name, sig)
        
        # Set function metadata for FastMCP
        dynamic_tool.__name__ = namespaced_name
        dynamic_tool.__doc__ = full_description
        
        # Register with FastMCP using decorator pattern
        self._mcp.tool(name=namespaced_name)(dynamic_tool)
        
        logger.debug(f"Registered dynamic tool: {namespaced_name}")
    
    async def _activate_tools_from_refs(self, tool_refs: List[Any]) -> None:
        """Activate deferred tools by registering them as live FastMCP tools.
        
        This is called after search discovers tools to make them callable.
        Idempotent - skips tools that are already registered.
        """
        for ref in tool_refs:
            namespaced_name = ref.namespaced_name
            
            # Skip if already activated
            if namespaced_name in self._active_tools:
                continue
            
            # Parse server and tool names
            if "__" not in namespaced_name:
                logger.warning(f"Invalid namespaced tool name: {namespaced_name}")
                continue
            
            server_name, tool_name = namespaced_name.split("__", 1)
            
            # Get tool metadata
            meta = await self._registry.get_tool_metadata(namespaced_name)
            if meta is None:
                logger.warning(f"Metadata not found for tool: {namespaced_name}")
                continue
            
            # Register as live FastMCP tool
            self._create_dynamic_tool(server_name, tool_name, meta)
            self._active_tools.add(namespaced_name)
            
            logger.debug(f"Activated deferred tool: {namespaced_name}")
    
    def get_mcp(self) -> FastMCP:
        """Get the FastMCP instance."""
        return self._mcp
    
    def run(self, transport: Literal["stdio", "http"] = "stdio", port: Optional[int] = None, host: str = "0.0.0.0") -> None:
        """Run the MCP server.
        
        Args:
            transport: Transport type ('stdio' or 'http')
            port: Port for HTTP transport
            host: Host for HTTP transport
        """
        if transport == "http" and port:
            # Use HTTP transport with CORS middleware for browser-based clients
            middleware = [
                Middleware(
                    CORSMiddleware,
                    allow_origins=["*"],  # Allow all origins for orchestrator
                    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                    allow_headers=[
                        "mcp-protocol-version",
                        "mcp-session-id",
                        "Authorization",
                        "Content-Type",
                    ],
                    expose_headers=["mcp-session-id"],
                )
            ]
            http_app = self._mcp.http_app(middleware=middleware)
            import uvicorn
            uvicorn.run(http_app, host=host, port=port, log_level="info")
        else:
            self._mcp.run(transport="stdio")


async def create_mcp_server(
    storage: StorageBackend,
    server_registry: ServerRegistry,
    tool_search: ToolSearchService,
) -> MCPOrchestratorServer:
    """Factory function to create and initialize the MCP Orchestrator server.

    Args:
        storage: Storage backend for persistent data
        server_registry: Server registry for managing MCP servers
        tool_search: Tool search service for regex and BM25 search

    Returns:
        Initialized MCPOrchestratorServer instance
    """
    server = MCPOrchestratorServer(storage, server_registry, tool_search)
    await server.register_dynamic_tools()
    return server
