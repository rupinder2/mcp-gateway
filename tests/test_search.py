"""Tests for tool search service."""

import pytest
from mcp_orchestrator.tools.search import ToolSearchService


@pytest.fixture
def search_service():
    """Create tool search service for testing."""
    return ToolSearchService()


def test_index_and_search_regex(search_service):
    """Test indexing and searching with regex."""
    # Index some tools
    tools = [
        {
            "name": "get_weather",
            "description": "Get weather for a location",
            "input_schema": {
                "properties": {
                    "location": {"type": "string", "description": "City name"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
                }
            }
        },
        {
            "name": "search_files",
            "description": "Search through files in workspace",
            "input_schema": {
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                }
            }
        },
        {
            "name": "send_email",
            "description": "Send an email message",
            "input_schema": {
                "properties": {
                    "to": {"type": "string", "description": "Recipient email"},
                    "subject": {"type": "string"}
                }
            }
        }
    ]
    
    search_service.index_tools("my-server", tools)
    
    # Search for weather
    results = search_service.search_regex("weather")
    assert len(results) == 1
    assert results[0].tool_name == "get_weather"
    
    # Search for files
    results = search_service.search_regex("file|search")
    assert len(results) == 1
    assert results[0].tool_name == "search_files"
    
    # Search with broader pattern
    results = search_service.search_regex("get.*")
    assert len(results) == 1


def test_search_regex_case_insensitive(search_service):
    """Test that regex search is case insensitive."""
    tools = [
        {
            "name": "GET_DATA",
            "description": "Get some data",
            "input_schema": {}
        }
    ]
    
    search_service.index_tools("test-server", tools)
    
    # Search with different case
    results = search_service.search_regex("get_data")
    assert len(results) == 1
    
    results = search_service.search_regex("GET_DATA")
    assert len(results) == 1


def test_search_regex_limit(search_service):
    """Test search result limit."""
    tools = [
        {"name": f"tool_{i}", "description": f"Tool number {i}", "input_schema": {}}
        for i in range(10)
    ]
    
    search_service.index_tools("test-server", tools)
    
    # Search with limit
    results = search_service.search_regex("tool.*", limit=3)
    assert len(results) == 3


def test_search_bm25(search_service):
    """Test BM25 search (falls back to simple scoring)."""
    tools = [
        {
            "name": "get_weather",
            "description": "Get current weather conditions",
            "input_schema": {
                "properties": {
                    "location": {"type": "string", "description": "City name"}
                }
            }
        },
        {
            "name": "get_forecast",
            "description": "Get weather forecast for upcoming days",
            "input_schema": {
                "properties": {
                    "days": {"type": "integer", "description": "Number of days"}
                }
            }
        },
        {
            "name": "send_email",
            "description": "Send an email",
            "input_schema": {}
        }
    ]
    
    search_service.index_tools("my-server", tools)
    
    # Search for weather
    results = search_service.search_bm25("weather", limit=5)
    assert len(results) >= 2  # Should find weather and forecast
    
    # First result should be most relevant (get_weather - name match)
    weather_tools = [r for r in results if "weather" in r.tool_name]
    assert len(weather_tools) >= 1


def test_get_all_tools(search_service):
    """Test getting all indexed tools."""
    tools = [
        {"name": "tool1", "description": "First tool", "input_schema": {}},
        {"name": "tool2", "description": "Second tool", "input_schema": {}},
    ]
    
    search_service.index_tools("server1", tools)
    
    all_tools = search_service.get_all_tools()
    assert len(all_tools) == 2


def test_get_tool(search_service):
    """Test getting a specific tool."""
    tools = [
        {"name": "my_tool", "description": "My tool", "input_schema": {"type": "object"}}
    ]
    
    search_service.index_tools("my-server", tools)
    
    tool = search_service.get_tool("my-server__my_tool")
    assert tool is not None
    assert tool.tool_name == "my_tool"
    assert tool.server_name == "my-server"


def test_get_nonexistent_tool(search_service):
    """Test getting a tool that doesn't exist."""
    tool = search_service.get_tool("server__nonexistent")
    assert tool is None


def test_remove_server_tools(search_service):
    """Test removing all tools from a server."""
    tools1 = [
        {"name": "tool1", "description": "Tool 1", "input_schema": {}},
    ]
    tools2 = [
        {"name": "tool2", "description": "Tool 2", "input_schema": {}},
    ]
    
    search_service.index_tools("server1", tools1)
    search_service.index_tools("server2", tools2)
    
    # Remove server1 tools
    search_service.remove_server_tools("server1")
    
    # server1 tools should be gone
    all_tools = search_service.get_all_tools()
    assert len(all_tools) == 1
    assert all_tools[0].server_name == "server2"


def test_invalid_regex_pattern(search_service):
    """Test that invalid regex raises ValueError."""
    with pytest.raises(ValueError, match="Invalid regex"):
        search_service.search_regex("[invalid")


def test_search_bm25_by_default(search_service):
    """Test unified search defaults to BM25."""
    tools = [
        {"name": "get_weather", "description": "Get weather information", "input_schema": {}},
        {"name": "search_docs", "description": "Search documentation", "input_schema": {}},
    ]
    
    search_service.index_tools("my-server", tools)
    
    # Default should use BM25
    results = search_service.search("weather")
    assert len(results) >= 1
    assert results[0].tool_name == "get_weather"


def test_search_regex_mode(search_service):
    """Test unified search with regex mode enabled."""
    tools = [
        {"name": "get_weather", "description": "Get weather", "input_schema": {}},
        {"name": "search_docs", "description": "Search docs", "input_schema": {}},
    ]
    
    search_service.index_tools("my-server", tools)
    
    results = search_service.search("get_.*", use_regex=True)
    assert len(results) == 1
    assert results[0].tool_name == "get_weather"


def test_search_regex_mode_invalid_pattern(search_service):
    """Test unified search with regex mode and invalid pattern."""
    with pytest.raises(ValueError, match="Invalid regex"):
        search_service.search("[invalid", use_regex=True)


def test_search_with_limit(search_service):
    """Test unified search respects limit parameter."""
    tools = [
        {"name": f"tool_{i}", "description": f"Tool {i}", "input_schema": {}}
        for i in range(10)
    ]
    
    search_service.index_tools("test-server", tools)
    
    results = search_service.search("tool.*", limit=3)
    assert len(results) == 3
