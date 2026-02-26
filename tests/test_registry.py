"""Tests for server registry."""

import pytest
from datetime import datetime
from mcp_orchestrator.models import ServerRegistration, AuthConfig
from mcp_orchestrator.server.registry import ServerRegistry
from mcp_orchestrator.storage.memory import InMemoryStorage


@pytest.fixture
async def storage():
    """Create in-memory storage for testing."""
    return InMemoryStorage()


@pytest.fixture
async def registry(storage):
    """Create server registry for testing."""
    return ServerRegistry(storage)


@pytest.mark.asyncio
async def test_register_server(registry):
    """Test registering a server."""
    registration = ServerRegistration(
        name="test-server",
        url="https://test.example.com",
        connection_mode="stateless",
        auth=AuthConfig(type="none"),
        auto_discover=True
    )
    
    server_info = await registry.register(registration)
    
    assert server_info.name == "test-server"
    assert server_info.url == "https://test.example.com"
    assert server_info.connection_mode == "stateless"
    assert server_info.auth_type == "none"
    assert server_info.status == "unknown"
    assert server_info.tool_count == 0
    assert isinstance(server_info.registered_at, datetime)


@pytest.mark.asyncio
async def test_register_duplicate_server(registry):
    """Test that registering duplicate server raises error."""
    registration = ServerRegistration(
        name="test-server",
        url="https://test.example.com",
        connection_mode="stateless"
    )
    
    await registry.register(registration)
    
    with pytest.raises(ValueError, match="already registered"):
        await registry.register(registration)


@pytest.mark.asyncio
async def test_unregister_server(registry):
    """Test unregistering a server."""
    registration = ServerRegistration(
        name="test-server",
        url="https://test.example.com",
        connection_mode="stateless"
    )
    
    await registry.register(registration)
    result = await registry.unregister("test-server")
    
    assert result is True
    
    # Verify server is gone
    server = await registry.get("test-server")
    assert server is None


@pytest.mark.asyncio
async def test_unregister_nonexistent_server(registry):
    """Test unregistering a server that doesn't exist."""
    result = await registry.unregister("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_list_servers(registry):
    """Test listing all servers."""
    # Register multiple servers
    servers = [
        ServerRegistration(name="server1", url="https://1.example.com"),
        ServerRegistration(name="server2", url="https://2.example.com"),
        ServerRegistration(name="server3", url="https://3.example.com"),
    ]
    
    for server in servers:
        await registry.register(server)
    
    all_servers = await registry.list_all()
    assert len(all_servers) == 3
    
    names = [s.name for s in all_servers]
    assert "server1" in names
    assert "server2" in names
    assert "server3" in names


@pytest.mark.asyncio
async def test_update_status(registry):
    """Test updating server status."""
    registration = ServerRegistration(
        name="test-server",
        url="https://test.example.com",
        connection_mode="stateless"
    )
    
    await registry.register(registration)
    
    result = await registry.update_status("test-server", "active")
    assert result is True
    
    server = await registry.get("test-server")
    assert server.status == "active"
    assert server.last_health_check is not None


@pytest.mark.asyncio
async def test_update_status_nonexistent(registry):
    """Test updating status for nonexistent server."""
    result = await registry.update_status("nonexistent", "active")
    assert result is False


@pytest.mark.asyncio
async def test_store_and_get_tools(registry):
    """Test storing and retrieving tools."""
    registration = ServerRegistration(
        name="test-server",
        url="https://test.example.com",
        connection_mode="stateless"
    )
    
    await registry.register(registration)
    
    tools = [
        {"name": "tool1", "description": "First tool"},
        {"name": "tool2", "description": "Second tool"},
    ]
    
    await registry.store_tools("test-server", tools)
    retrieved = await registry.get_tools("test-server")
    
    assert len(retrieved) == 2
    assert retrieved[0]["name"] == "tool1"
    assert retrieved[1]["name"] == "tool2"


@pytest.mark.asyncio
async def test_get_auth_config(registry):
    """Test retrieving auth config."""
    registration = ServerRegistration(
        name="test-server",
        url="https://test.example.com",
        connection_mode="stateless",
        auth=AuthConfig(
            type="static",
            headers={"Authorization": "Bearer token123"}
        )
    )
    
    await registry.register(registration)
    
    auth_config = await registry.get_auth_config("test-server")
    assert auth_config is not None
    assert auth_config.type == "static"
    assert auth_config.headers["Authorization"] == "Bearer token123"
