"""Test configuration and models."""

import pytest
from pydantic import ValidationError
from mcp_orchestrator.models import (
    AuthConfig,
    ServerRegistration,
    ServerInfo,
    ToolReference,
    ToolSearchRequest,
    OrchestratorConfig,
)


def test_auth_config_defaults():
    """Test AuthConfig default values."""
    auth = AuthConfig()
    assert auth.type == "none"
    assert auth.headers is None
    assert auth.header_name == "Authorization"
    assert auth.header_prefix == "Bearer"


def test_auth_config_static():
    """Test AuthConfig with static auth."""
    auth = AuthConfig(
        type="static",
        headers={"Authorization": "Bearer token123"}
    )
    assert auth.type == "static"
    assert auth.headers["Authorization"] == "Bearer token123"


def test_server_registration_validation():
    """Test ServerRegistration validation."""
    # Valid registration
    reg = ServerRegistration(
        name="test-server",
        url="https://test.example.com"
    )
    assert reg.name == "test-server"
    assert reg.url == "https://test.example.com"
    assert reg.connection_mode == "stateless"  # default
    assert reg.auto_discover is True  # default


def test_server_registration_empty_name():
    """Test that empty name raises validation error."""
    with pytest.raises(ValidationError):
        ServerRegistration(name="", url="https://test.example.com")


def test_server_info_creation():
    """Test ServerInfo creation."""
    from datetime import datetime
    
    info = ServerInfo(
        name="test-server",
        url="https://test.example.com",
        connection_mode="stateful",
        auth_type="static",
        status="active",
        registered_at=datetime.utcnow(),
        tool_count=5
    )
    
    assert info.name == "test-server"
    assert info.status == "active"
    assert info.tool_count == 5


def test_tool_reference():
    """Test ToolReference creation."""
    ref = ToolReference(
        server_name="my-server",
        tool_name="my_tool",
        namespaced_name="my-server__my_tool",
        description="A test tool",
        input_schema={"type": "object"},
        defer_loading=True
    )
    
    assert ref.server_name == "my-server"
    assert ref.tool_name == "my_tool"
    assert ref.namespaced_name == "my-server__my_tool"
    assert ref.defer_loading is True


def test_tool_search_request_validation():
    """Test ToolSearchRequest validation."""
    # Valid request
    req = ToolSearchRequest(query="weather search")
    assert req.query == "weather search"
    assert req.search_type == "bm25"  # default
    assert req.limit == 5  # default
    
    # Custom values
    req = ToolSearchRequest(
        query="test",
        search_type="regex",
        limit=10
    )
    assert req.search_type == "regex"
    assert req.limit == 10


def test_tool_search_request_limit_bounds():
    """Test ToolSearchRequest limit bounds."""
    # Limit too low
    with pytest.raises(ValidationError):
        ToolSearchRequest(query="test", limit=0)
    
    # Limit too high
    with pytest.raises(ValidationError):
        ToolSearchRequest(query="test", limit=21)


def test_tool_search_request_query_length():
    """Test ToolSearchRequest query length limit."""
    # Query too long (>200 chars)
    with pytest.raises(ValidationError):
        ToolSearchRequest(query="a" * 201)


def test_orchestrator_config_defaults():
    """Test OrchestratorConfig default values."""
    config = OrchestratorConfig()
    
    assert config.storage_backend == "memory"
    assert config.tool_cache_ttl == 300
    assert config.default_connection_mode == "stateless"
    assert config.connection_timeout == 30.0
    assert config.max_retries == 3
    assert config.http_host == "0.0.0.0"
    assert config.http_port == 8000
    assert config.mcp_transport == "stdio"
    assert config.log_level == "INFO"
