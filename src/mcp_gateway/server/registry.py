"""Server registry for managing MCP servers.

This module provides the ServerRegistry class which manages the registration,
discovery, and lifecycle of downstream MCP servers.

Key operations:
- Register new servers with auth configuration
- Unregister servers and clean up associated data
- Store and retrieve tool metadata
- Track server health status

Usage:
    registry = ServerRegistry(storage)
    
    # Register a server
    registration = ServerRegistration(
        name="my-server",
        url="http://localhost:8080/mcp",
        transport="http",
    )
    await registry.register(registration)
    
    # Discover and store tools
    await registry.store_tools("my-server", [{"name": "tool1", ...}])
    
    # List all servers
    servers = await registry.list_all()

Storage keys used:
- gateway:servers - Hash of all registered servers
- gateway:server:{name}:auth - Auth configuration for a server
- gateway:server:{name}:tools - Tool list for a server
- gateway:tool_meta:{namespaced_name} - Metadata for individual tools
"""

from datetime import datetime
from typing import Optional, Dict, List, Literal, Any
from ..models import ServerInfo, ServerRegistration, AuthConfig
from ..storage.base import StorageBackend

ServerStatus = Literal["active", "inactive", "error", "unknown"]


class ServerRegistry:
    """Registry for managing MCP servers."""
    
    def __init__(self, storage: StorageBackend):
        self._storage = storage
        self._servers_key = "gateway:servers"
    
    async def register(self, registration: ServerRegistration) -> ServerInfo:
        """Register a new MCP server."""
        # Check if server already exists
        existing = await self.get(registration.name)
        if existing:
            raise ValueError(f"Server '{registration.name}' already registered")
        
        # Create server info
        server_info = ServerInfo(
            name=registration.name,
            url=registration.url,
            transport=registration.transport,
            command=registration.command,
            args=registration.args,
            env=registration.env,
            connection_mode=registration.connection_mode,
            auth_type=registration.auth.type,
            status="unknown",
            registered_at=datetime.utcnow(),
            tool_count=0
        )
        
        # Store server info
        await self._storage.hset(
            self._servers_key,
            registration.name,
            server_info.model_dump()
        )
        
        # Store auth config separately
        if registration.auth.type != "none":
            await self._storage.hset(
                f"gateway:server:{registration.name}:auth",
                "config",
                registration.auth.model_dump()
            )
        
        return server_info
    
    async def unregister(self, name: str) -> bool:
        """Unregister an MCP server."""
        # Check if server exists
        existing = await self.get(name)
        if not existing:
            return False
        
        # Remove server info
        await self._storage.hdel(self._servers_key, name)
        
        # Remove auth config
        await self._storage.delete(f"gateway:server:{name}:auth")
        
        # Remove tools
        await self._storage.delete(f"gateway:server:{name}:tools")
        
        # Remove tool metadata
        await self.remove_tool_metadata(name)
        
        return True
    
    async def get(self, name: str) -> Optional[ServerInfo]:
        """Get server info by name."""
        data = await self._storage.hget(self._servers_key, name)
        if data:
            return ServerInfo.model_validate(data)
        return None
    
    async def list_all(self) -> List[ServerInfo]:
        """List all registered servers."""
        servers_data = await self._storage.hgetall(self._servers_key)
        return [
            ServerInfo.model_validate(data)
            for data in servers_data.values()
        ]
    
    async def update_status(
        self,
        name: str,
        status: ServerStatus,
        error_message: Optional[str] = None
    ) -> bool:
        """Update server health status."""
        server = await self.get(name)
        if not server:
            return False
        
        # Create updated server info
        updated_data = server.model_dump()
        updated_data["status"] = status
        updated_data["last_health_check"] = datetime.utcnow().isoformat()
        if error_message:
            updated_data["error_message"] = error_message
        
        updated_server = ServerInfo.model_validate(updated_data)
        
        await self._storage.hset(
            self._servers_key,
            name,
            updated_server.model_dump()
        )
        return True
    
    async def update_tool_count(self, name: str, count: int) -> bool:
        """Update server tool count."""
        server = await self.get(name)
        if not server:
            return False
        
        server.tool_count = count
        await self._storage.hset(
            self._servers_key,
            name,
            server.model_dump()
        )
        return True
    
    async def get_auth_config(self, name: str) -> Optional[AuthConfig]:
        """Get auth config for a server."""
        data = await self._storage.hget(
            f"gateway:server:{name}:auth",
            "config"
        )
        if data:
            return AuthConfig.model_validate(data)
        return None
    
    async def store_tools(self, name: str, tools: List[Dict]) -> None:
        """Store tools for a server and their metadata.
        
        Stores both the full tools list and individual metadata entries.
        """
        # Store the full tools list
        await self._storage.set(
            f"gateway:server:{name}:tools",
            tools
        )
        
        # Store metadata for each tool
        for tool in tools:
            tool_name = tool.get("name")
            if tool_name:
                await self.store_tool_metadata(name, tool_name, tool)
    
    async def get_tools(self, name: str) -> List[Dict]:
        """Get tools for a server."""
        tools = await self._storage.get(f"gateway:server:{name}:tools")
        return tools or []

    async def store_tool_metadata(
        self,
        server_name: str,
        tool_name: str,
        tool_data: Dict[str, Any],
    ) -> None:
        """Store tool metadata without registering it as a live FastMCP tool.
        
        tool_data must include:
          - description: str
          - input_schema: Dict (JSON schema object)
        
        Storage key format: tool_meta:{server_name}__{tool_name}
        """
        namespaced_name = f"{server_name}__{tool_name}"
        metadata = {
            "namespaced_name": namespaced_name,
            "server_name": server_name,
            "tool_name": tool_name,
            "description": tool_data.get("description", ""),
            "input_schema": tool_data.get("input_schema", {}),
        }
        await self._storage.set(f"gateway:tool_meta:{namespaced_name}", metadata)
    
    async def get_tool_metadata(
        self,
        namespaced_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Retrieve stored metadata for a tool by its namespaced name.
        Returns None if not found.
        """
        metadata = await self._storage.get(f"gateway:tool_meta:{namespaced_name}")
        return metadata
    
    async def get_all_tool_metadata(self) -> List[Dict[str, Any]]:
        """Return metadata for ALL tools across ALL servers.
        Each entry must include: namespaced_name, description, input_schema, server_name.
        Used by the search index to build/rebuild the corpus.
        """
        # Scan for all tool metadata keys
        all_metadata = []
        pattern = "gateway:tool_meta:*"
        
        # Get all keys matching the pattern
        keys = await self._storage.keys(pattern)
        
        for key in keys:
            metadata = await self._storage.get(key)
            if metadata:
                all_metadata.append(metadata)
        
        return all_metadata
    
    async def remove_tool_metadata(self, server_name: str) -> None:
        """Remove all tool metadata for a server."""
        pattern = f"gateway:tool_meta:{server_name}__*"
        keys = await self._storage.keys(pattern)
        for key in keys:
            await self._storage.delete(key)
