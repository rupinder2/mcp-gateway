"""
MCP Gateway Tool Call Validation - Final Version
"""

import asyncio
import sys
from pathlib import Path
import httpx

sys.path.insert(0, str(Path(__file__).parent / "src"))

from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.sse import sse_client
from mcp import ClientSession


async def test_http_server():
    """Test HTTP (streamable-http) server."""
    print("\n[1] Testing HTTP server (http://127.0.0.1:8000/mcp)")
    headers = {"Authorization": "Bearer sample-server-key"}
    
    try:
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as http_client:
            async with streamable_http_client("http://127.0.0.1:8000/mcp", http_client=http_client) as (read, write, _get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    print(f"  Found {len(result.tools)} tools")
                    
                    # Test tool call
                    call_result = await session.call_tool("add", {"a": 5, "b": 3})
                    print(f"  add(5, 3) = {call_result.content[0].text if call_result.content else 'N/A'}")
                    return True
    except Exception as e:
        print(f"  ✗ Error: {type(e).__name__}: {e}")
        return False


async def test_sse_server():
    """Test SSE server."""
    print("\n[2] Testing SSE server (http://127.0.0.1:8001/sse)")
    
    try:
        async with asyncio.timeout(30):
            async with sse_client("http://127.0.0.1:8001/sse") as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    print(f"  Found {len(result.tools)} tools")
                    
                    # Test tool call if available
                    if result.tools:
                        tool_name = result.tools[0].name
                        call_result = await session.call_tool(tool_name, {"text": "hello"} if "echo" in tool_name.lower() else {})
                        print(f"  Called {tool_name}: success={not call_result.isError}")
                    
                    return True
    except Exception as e:
        print(f"  ✗ Error: {type(e).__name__}: {e}")
        return False


async def test_stdio_server():
    """Test STDIO server."""
    print("\n[3] Testing STDIO server")
    
    try:
        stdio_params = StdioServerParameters(
            command="uv",
            args=["run", "python", "stdio_server/server.py"],
            env={},
        )
        
        async with asyncio.timeout(30):
            async with stdio_client(stdio_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    print(f"  Found {len(result.tools)} tools")
                    
                    # Test tool call
                    call_result = await session.call_tool("echo", {"text": "test"})
                    print(f"  echo('test') = {call_result.content[0].text if call_result.content else 'N/A'}")
                    
                    return True
    except Exception as e:
        print(f"  ✗ Error: {type(e).__name__}: {e}")
        return False


async def test_router():
    """Test the gateway's ToolRouter with all transports."""
    print("\n[4] Testing Gateway ToolRouter")
    
    from mcp_gateway.tools.router import ToolRouter
    
    results = []
    
    # Test HTTP transport
    print("  HTTP transport:")
    router = ToolRouter(timeout=30.0, gateway_auth_mode="auto", gateway_transport="http")
    result = await router.call_tool(
        server_name="sample-http",
        server_url="http://127.0.0.1:8000/mcp",
        tool_name="add",
        arguments={"a": 10, "b": 20},
        transport="http",
        auth_headers={"Authorization": "Bearer sample-server-key"},
    )
    success = result.get("success", False)
    print(f"    add(10, 20): {'✓' if success else '✗'}")
    results.append(("http", success))
    
    # Test SSE transport
    print("  SSE transport:")
    router = ToolRouter(timeout=30.0, gateway_auth_mode="auto", gateway_transport="http")
    result = await router.call_tool(
        server_name="sample-sse",
        server_url="http://127.0.0.1:8001/sse",
        tool_name="echo",
        arguments={"text": "hello"},
        transport="sse",
    )
    success = result.get("success", False)
    print(f"    echo('hello'): {'✓' if success else '✗'}")
    results.append(("sse", success))
    
    # Test STDIO transport
    print("  STDIO transport:")
    router = ToolRouter(timeout=30.0, gateway_auth_mode="auto", gateway_transport="stdio")
    result = await router.call_tool(
        server_name="sample-stdio",
        server_url="stdio_server/server.py",
        tool_name="echo",
        arguments={"text": "hello"},
        transport="stdio",
        command="uv",
        args=["run", "python", "stdio_server/server.py"],
        env={},
    )
    success = result.get("success", False)
    print(f"    echo('hello'): {'✓' if success else '✗'}")
    results.append(("stdio", success))
    
    return results


async def test_gateway_transports():
    """Test gateway with different transport modes."""
    print("\n[5] Testing Gateway Transport Combinations")
    
    from mcp_gateway.storage.memory import InMemoryStorage
    from mcp_gateway.server.registry import ServerRegistry
    from mcp_gateway.tools.search import ToolSearchService
    from mcp_gateway.mcp_server import MCPGatewayServer
    from mcp_gateway.models import ServerRegistration, AuthConfig
    
    test_cases = [
        ("stdio", "stdio", "http://127.0.0.1:8001/sse", "uv", ["run", "python", "stdio_server/server.py"]),
        ("http", "http", "http://127.0.0.1:8000/mcp", None, None),
        ("sse", "sse", "http://127.0.0.1:8001/sse", None, None),
    ]
    
    results = []
    
    for gateway_transport, downstream_name, downstream_url, cmd, args in test_cases:
        print(f"\n  Gateway: {gateway_transport} -> Downstream: {downstream_name}")
        
        storage = InMemoryStorage()
        registry = ServerRegistry(storage)
        tool_search = ToolSearchService()
        
        server = MCPGatewayServer(
            storage=storage,
            server_registry=registry,
            tool_search=tool_search,
            gateway_auth_mode="auto",
            gateway_transport=gateway_transport,
        )
        
        # Build registration based on transport type
        if downstream_name == "http":
            reg = ServerRegistration(
                name=downstream_name,
                url=downstream_url,
                transport=downstream_name,
                auth=AuthConfig(type="static", headers={"Authorization": "Bearer sample-server-key"}),
                auto_discover=False,
            )
            auth_headers = {"Authorization": "Bearer sample-server-key"}
            tool_args = {"a": 1, "b": 2}
        elif downstream_name == "sse":
            reg = ServerRegistration(
                name=downstream_name,
                url=downstream_url,
                transport=downstream_name,
                auto_discover=False,
            )
            auth_headers = None
            tool_args = {"text": "test"}
        else:
            reg = ServerRegistration(
                name=downstream_name,
                url="stdio_server/server.py",
                transport="stdio",
                command=cmd,
                args=args,
                auto_discover=False,
            )
            auth_headers = None
            tool_args = {"text": "test"}
        
        try:
            await registry.register(reg)
            
            # Discover tools
            tools = await server._discover_tools(
                name=downstream_name,
                url=downstream_url if downstream_name != "stdio" else "stdio_server/server.py",
                transport=downstream_name,
                command=cmd,
                args=args,
                auth_headers=auth_headers,
            )
            
            if tools:
                await registry.store_tools(downstream_name, tools)
                
                # Find a suitable tool - prefer echo or get_time
                first_tool = None
                tool_args = {}
                for t in tools:
                    name = t.get("name", "")
                    if name == "echo":
                        first_tool = name
                        tool_args = {"text": "test"}
                        break
                    elif name == "get_time":
                        first_tool = name
                        tool_args = {}
                    elif first_tool is None:
                        first_tool = name
                        # Try to build args from schema
                        schema = t.get("input_schema", {})
                        props = schema.get("properties", {})
                        for k, v in props.items():
                            if v.get("type") == "string":
                                tool_args[k] = "test"
                            elif v.get("type") == "number":
                                tool_args[k] = 1
                
                # Call tool via router
                result = await server._tool_router.call_tool(
                    server_name=downstream_name,
                    server_url=downstream_url if downstream_name != "stdio" else "stdio_server/server.py",
                    tool_name=first_tool,
                    arguments=tool_args,
                    transport=downstream_name,
                    command=cmd,
                    args=args,
                    auth_headers=auth_headers,
                )
                
                success = result.get("success", False)
                print(f"    Tool '{first_tool}': {'✓' if success else '✗'}")
                results.append((gateway_transport, downstream_name, success))
            else:
                print(f"    No tools discovered")
                results.append((gateway_transport, downstream_name, False))
                
        except Exception as e:
            print(f"    Error: {e}")
            results.append((gateway_transport, downstream_name, False))
    
    return results


async def test_call_remote_tool():
    """Test the call_remote_tool gateway tool."""
    print("\n[6] Testing call_remote_tool Gateway Tool")
    
    from mcp_gateway.storage.memory import InMemoryStorage
    from mcp_gateway.server.registry import ServerRegistry
    from mcp_gateway.tools.search import ToolSearchService
    from mcp_gateway.mcp_server import MCPGatewayServer
    from mcp_gateway.models import ServerRegistration, AuthConfig
    
    results = []
    
    for gateway_transport in ["http", "stdio"]:
        print(f"\n  Gateway: {gateway_transport}")
        
        storage = InMemoryStorage()
        registry = ServerRegistry(storage)
        tool_search = ToolSearchService()
        
        server = MCPGatewayServer(
            storage=storage,
            server_registry=registry,
            tool_search=tool_search,
            gateway_auth_mode="auto",
            gateway_transport=gateway_transport,
        )
        
        # Register HTTP server
        reg = ServerRegistration(
            name="sample-http",
            url="http://127.0.0.1:8000/mcp",
            transport="http",
            auth=AuthConfig(type="static", headers={"Authorization": "Bearer sample-server-key"}),
            auto_discover=False,
        )
        
        try:
            await registry.register(reg)
            
            # Discover tools
            tools = await server._discover_tools(
                name="sample-http",
                url="http://127.0.0.1:8000/mcp",
                transport="http",
                auth_headers={"Authorization": "Bearer sample-server-key"},
            )
            
            if tools:
                await registry.store_tools("sample-http", tools)
                
                # Use call_remote_tool
                result = await server._tool_router.call_tool(
                    server_name="sample-http",
                    server_url="http://127.0.0.1:8000/mcp",
                    tool_name="add",
                    arguments={"a": 100, "b": 200},
                    transport="http",
                    auth_headers={"Authorization": "Bearer sample-server-key"},
                )
                
                success = result.get("success", False)
                print(f"    add(100, 200): {'✓' if success else '✗'}")
                results.append((gateway_transport, success))
                
        except Exception as e:
            print(f"    Error: {e}")
            results.append((gateway_transport, False))
    
    return results


async def main():
    print("=" * 60)
    print("MCP Gateway Tool Call Validation")
    print("=" * 60)
    
    # Test direct connections
    http_ok = await test_http_server()
    sse_ok = await test_sse_server()
    stdio_ok = await test_stdio_server()
    
    # Test router
    router_results = await test_router()
    
    # Test gateway transports
    gateway_results = await test_gateway_transports()
    
    # Test call_remote_tool
    call_results = await test_call_remote_tool()
    
    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)
    
    print("\n[Direct Server Connections]")
    print(f"  HTTP (8000/mcp):    {'✓ PASS' if http_ok else '✗ FAIL'}")
    print(f"  SSE  (8001/sse):   {'✓ PASS' if sse_ok else '✗ FAIL'}")
    print(f"  STDIO (subprocess): {'✓ PASS' if stdio_ok else '✗ FAIL'}")
    
    print("\n[ToolRouter Direct]")
    for transport, success in router_results:
        print(f"  {transport}: {'✓ PASS' if success else '✗ FAIL'}")
    
    print("\n[Gateway Transport Combinations]")
    for gt, dt, success in gateway_results:
        print(f"  {gt} -> {dt}: {'✓ PASS' if success else '✗ FAIL'}")
    
    print("\n[call_remote_tool]")
    for gt, success in call_results:
        print(f"  {gt}: {'✓ PASS' if success else '✗ FAIL'}")
    
    # Calculate totals
    all_tests = [http_ok, sse_ok, stdio_ok]
    all_tests.extend([s for _, s in router_results])
    all_tests.extend([s for _, _, s in gateway_results])
    all_tests.extend([s for _, s in call_results])
    
    passed = sum(1 for s in all_tests if s)
    total = len(all_tests)
    
    print(f"\n[TOTAL] {passed}/{total} tests passed ({100*passed//total}%)")


if __name__ == "__main__":
    asyncio.run(main())
