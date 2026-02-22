"""Main entry point for MCP Gateway."""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .config_loader import ServerConfigLoader
from .models import GatewayConfig
from .mcp_server import MCPGatewayServer
from .server.registry import ServerRegistry
from .storage.base import StorageBackend
from .storage.memory import InMemoryStorage
from .storage.redis import RedisStorage
from .tools.search import ToolSearchService

# Load .env file if it exists
load_dotenv()


def setup_logging(log_level: str = "INFO") -> None:
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)]
    )


def create_storage(config: GatewayConfig) -> StorageBackend:
    """Create storage backend based on configuration."""
    if config.storage_backend == "redis":
        return RedisStorage(config.redis_url or "redis://localhost:6379/0")
    return InMemoryStorage()


def create_config_from_env() -> GatewayConfig:
    """Create configuration from environment variables."""
    
    return GatewayConfig(
        storage_backend=os.getenv("STORAGE_BACKEND", "memory"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        tool_cache_ttl=int(os.getenv("MCP_GATEWAY_TOOL_CACHE_TTL", "300")),
        default_connection_mode=os.getenv("MCP_GATEWAY_DEFAULT_CONNECTION_MODE", "stateless"),
        connection_timeout=float(os.getenv("MCP_GATEWAY_CONNECTION_TIMEOUT", "30.0")),
        max_retries=int(os.getenv("MCP_GATEWAY_MAX_RETRIES", "3")),
        http_host=os.getenv("GATEWAY_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.getenv("GATEWAY_PORT", "8080")),
        mcp_transport=os.getenv("GATEWAY_TRANSPORT", "stdio"),
        gateway_auth_mode=os.getenv("GATEWAY_AUTH_MODE", "auto"),
        server_config_path=os.getenv("SERVER_CONFIG_PATH", "server_config.json"),
        log_level=os.getenv("GATEWAY_LOG_LEVEL", "INFO"),
    )


def main() -> None:
    """Main entry point."""
    # Create configuration from environment
    config = create_config_from_env()
    
    # Setup logging
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)
    
    logger.info("Starting MCP Gateway...")
    logger.info(f"Storage backend: {config.storage_backend}")
    
    # Create storage backend
    storage = create_storage(config)
    
    try:
        # Create server registry
        registry = ServerRegistry(storage)
        
        # Create tool search service
        tool_search = ToolSearchService()
        
        # Create MCP server
        server = MCPGatewayServer(storage, registry, tool_search, config.gateway_auth_mode, config.mcp_transport)
        
        logger.info("MCP Gateway server initialized")
        logger.info(f"Running with {config.mcp_transport} transport")
        
        # Load server configuration from file if provided
        if config.server_config_path:
            config_path = Path(config.server_config_path)
            if config_path.exists():
                logger.info(f"Loading server configuration from: {config_path}")
                config_loader = ServerConfigLoader(config_path)
                
                # Run the async config loader
                load_result = asyncio.run(
                    config_loader.load_and_register(registry, tool_search, server)
                )
                
                logger.info(
                    f"Server config loaded: {load_result['servers_loaded']} loaded, "
                    f"{load_result['servers_failed']} failed, {load_result['servers_skipped']} skipped, "
                    f"{load_result['total_tools']} total tools"
                )
                
                if load_result["servers"]:
                    server_list = [s["name"] for s in load_result["servers"]]
                    logger.info(f"Pre-configured servers: {server_list}")
            else:
                logger.debug(f"Server config file not found: {config_path}, skipping")
        
        # Run the server (FastMCP handles its own event loop)
        if config.mcp_transport == "http":
            server.run(transport=config.mcp_transport, port=config.http_port, host=config.http_host)
        else:
            server.run(transport=config.mcp_transport)
        
    except KeyboardInterrupt:
        logger.info("Shutting down MCP Gateway...")
    except Exception as e:
        logger.exception(f"Error running MCP Gateway: {e}")
        sys.exit(1)
    finally:
        # Cleanup
        asyncio.run(storage.close())


if __name__ == "__main__":
    main()
