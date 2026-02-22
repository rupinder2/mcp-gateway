"""Server configuration file loader for MCP Gateway.

Allows pre-configuring servers at startup via a JSON configuration file.
"""

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .models import AuthConfig, ServerConfigEntry, ServerConfigFile, ServerRegistration
from .server.registry import ServerRegistry
from .tools.search import ToolSearchService

if TYPE_CHECKING:
    from .mcp_server import MCPGatewayServer

logger = logging.getLogger(__name__)


class ServerConfigLoader:
    """Loads and registers servers from a configuration file."""
    
    def __init__(self, config_path: Path):
        """Initialize the config loader.
        
        Args:
            config_path: Path to the server configuration JSON file
        """
        self.config_path = config_path
    
    async def load_and_register(
        self,
        registry: ServerRegistry,
        tool_search: ToolSearchService,
        mcp_server: "MCPGatewayServer",
    ) -> Dict[str, Any]:
        """Load servers from config file and register them.
        
        Args:
            registry: ServerRegistry instance
            tool_search: ToolSearchService for indexing tools
            mcp_server: MCPGatewayServer instance for tool discovery
        
        Returns:
            Summary dict with servers_loaded, servers_failed, servers_skipped, total_tools
        """
        if not self.config_path.exists():
            logger.info(f"Server config file not found: {self.config_path}")
            return {
                "servers_loaded": 0,
                "servers_failed": 0,
                "servers_skipped": 0,
                "total_tools": 0,
                "servers": [],
            }
        
        try:
            with open(self.config_path, "r") as f:
                config_data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse server config: {e}")
            return {
                "servers_loaded": 0,
                "servers_failed": 0,
                "servers_skipped": 0,
                "total_tools": 0,
                "servers": [],
            }
        
        try:
            config = ServerConfigFile.model_validate(config_data)
        except Exception as e:
            logger.error(f"Invalid server config: {e}")
            return {
                "servers_loaded": 0,
                "servers_failed": 0,
                "servers_skipped": 0,
                "total_tools": 0,
                "servers": [],
            }
        
        servers_loaded = 0
        servers_failed = 0
        servers_skipped = 0
        total_tools = 0
        loaded_servers: List[Dict[str, Any]] = []
        
        for entry in config.servers:
            if not entry.enabled:
                logger.debug(f"Skipping disabled server: {entry.name}")
                servers_skipped += 1
                continue
            
            result = await self._register_server(
                entry=entry,
                registry=registry,
                tool_search=tool_search,
                mcp_server=mcp_server,
            )
            
            if result["success"]:
                servers_loaded += 1
                total_tools += result["tool_count"]
                loaded_servers.append({
                    "name": entry.name,
                    "url": entry.url,
                    "transport": entry.transport,
                    "tool_count": result["tool_count"],
                })
            else:
                servers_failed += 1
                logger.warning(f"Failed to load server '{entry.name}': {result['error']}")
        
        logger.info(
            f"Server config loaded: {servers_loaded} loaded, "
            f"{servers_failed} failed, {servers_skipped} skipped, "
            f"{total_tools} total tools"
        )
        
        if loaded_servers:
            server_names = [s["name"] for s in loaded_servers]
            logger.info(f"Servers: {server_names}")
            tool_summary = ", ".join([f"{s['name']}({s['tool_count']} tools)" for s in loaded_servers])
            logger.info(f"Tool summary: {tool_summary}")
        
        return {
            "servers_loaded": servers_loaded,
            "servers_failed": servers_failed,
            "servers_skipped": servers_skipped,
            "total_tools": total_tools,
            "servers": loaded_servers,
        }
    
    async def _register_server(
        self,
        entry: ServerConfigEntry,
        registry: ServerRegistry,
        tool_search: ToolSearchService,
        mcp_server: "MCPGatewayServer",
    ) -> Dict[str, Any]:
        """Register a single server from config.
        
        Args:
            entry: ServerConfigEntry from the config
            registry: ServerRegistry instance
            tool_search: ToolSearchService for indexing tools
            mcp_server: MCPGatewayServer instance
        
        Returns:
            Dict with success, error, tool_count
        """
        try:
            auth_config = AuthConfig(
                type=entry.auth_type,
                headers=entry.auth_headers,
                header_name=entry.auth_header_name,
            )
            
            registration = ServerRegistration(
                name=entry.name,
                url=entry.url,
                transport=entry.transport,
                command=entry.command,
                args=entry.args,
                env=entry.env,
                connection_mode=entry.connection_mode,
                auth=auth_config,
                auto_discover=entry.auto_discover,
            )
            
            await registry.register(registration)
            logger.info(f"Registered server '{entry.name}' from config")
            
            tool_count = 0
            if entry.auto_discover:
                try:
                    tools = await mcp_server._discover_tools(
                        name=entry.name,
                        url=entry.url,
                        transport=entry.transport,
                        command=entry.command,
                        args=entry.args,
                        env=entry.env,
                        auth_headers=entry.auth_headers,
                    )
                    
                    if tools:
                        await registry.store_tools(entry.name, tools)
                        tool_search.index_tools(entry.name, tools)
                        await registry.update_tool_count(entry.name, len(tools))
                        
                        tool_count = len(tools)
                        
                        # Only create dynamic tools if expose_tools is enabled
                        # Otherwise, tools are available via call_remote_tool and search only
                        if entry.expose_tools:
                            for tool_data in tools:
                                tool_name = tool_data.get("name")
                                if tool_name:
                                    try:
                                        mcp_server._create_dynamic_tool(entry.name, tool_name, tool_data)
                                    except Exception as e:
                                        logger.warning(f"Failed to create dynamic tool '{tool_name}': {e}")
                            logger.info(f"Exposed {tool_count} tools from '{entry.name}' in tools/list")
                        else:
                            logger.info(f"Registered {tool_count} tools from '{entry.name}' (use call_remote_tool to invoke)")
                except Exception as e:
                    logger.warning(f"Tool discovery failed for '{entry.name}': {e}")
            
            return {
                "success": True,
                "error": None,
                "tool_count": tool_count,
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "tool_count": 0,
            }
