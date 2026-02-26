"""
MCP Orchestrator Tool Call Validation - Final Version
"""

import asyncio
import sys
from pathlib import Path
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent / "src"))

from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession


@pytest.mark.skip(
    reason="Requires running MCP server - run manually for integration testing"
)
async def test_http_server():
    """Test HTTP server."""
    print("\n[1] Testing HTTP server (http://127.0.0.1:8000/mcp)")
    headers = {"Authorization": "Bearer sample-server-key"}

    try:
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as http_client:
            async with streamable_http_client(
                "http://127.0.0.1:8000/mcp", http_client=http_client
            ) as (read, write, _get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    print(f"  Found {len(result.tools)} tools")

                    # Test tool call
                    call_result = await session.call_tool("add", {"a": 5, "b": 3})
                    print(
                        f"  add(5, 3) = {call_result.content[0].text if call_result.content else 'N/A'}"
                    )
                    return True
    except Exception as e:
        print(f"  ✗ Error: {type(e).__name__}: {e}")
        return False


@pytest.mark.skip(
    reason="Requires running MCP server - run manually for integration testing"
)
async def test_stdio_server():
    """Test STDIO server."""
    print("\n[2] Testing STDIO server")

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
                    print(
                        f"  echo('test') = {call_result.content[0].text if call_result.content else 'N/A'}"
                    )

                    return True
    except Exception as e:
        print(f"  ✗ Error: {type(e).__name__}: {e}")
        return False


@pytest.mark.skip(
    reason="Requires running MCP server - run manually for integration testing"
)
async def test_router():
    """Test the orchestrator's ToolRouter with HTTP and stdio transports."""
    print("\n[3] Testing Orchestrator ToolRouter")

    from mcp_orchestrator.tools.router import ToolRouter

    results = []

    # Test HTTP transport
    print("  HTTP transport:")
    router = ToolRouter(
        timeout=30.0, auth_mode="auto", transport="http"
    )
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

    # Test STDIO transport
    print("  STDIO transport:")
    router = ToolRouter(
        timeout=30.0, auth_mode="auto", transport="stdio"
    )
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


@pytest.mark.skip(
    reason="Requires running MCP server - run manually for integration testing"
)
async def test_transports():
    """Test orchestrator with different transport modes."""
    print("\n[4] Testing Orchestrator Transport Combinations")

    from mcp_orchestrator.storage.memory import InMemoryStorage
    from mcp_orchestrator.server.registry import ServerRegistry
    from mcp_orchestrator.tools.search import ToolSearchService
    from mcp_orchestrator.mcp_server import MCPOrchestratorServer
    from mcp_orchestrator.models import ServerRegistration, AuthConfig

    test_cases = [
        (
            "stdio",
            "stdio",
            "stdio_server/server.py",
            "uv",
            ["run", "python", "stdio_server/server.py"],
        ),
        ("http", "http", "http://127.0.0.1:8000/mcp", None, None),
    ]

    results = []

    for transport, downstream_name, downstream_url, cmd, args in test_cases:
        print(f"\n  Orchestrator: {transport} -> Downstream: {downstream_name}")

        storage = InMemoryStorage()
        registry = ServerRegistry(storage)
        tool_search = ToolSearchService()

        server = MCPOrchestratorServer(
            storage=storage,
            server_registry=registry,
            tool_search=tool_search,
            auth_mode="auto",
            transport=transport,
        )

        # Build registration based on transport type
        if downstream_name == "http":
            reg = ServerRegistration(
                name=downstream_name,
                url=downstream_url,
                transport=downstream_name,
                auth=AuthConfig(
                    type="static", headers={"Authorization": "Bearer sample-server-key"}
                ),
                auto_discover=False,
            )
            auth_headers = {"Authorization": "Bearer sample-server-key"}
            tool_args = {"a": 1, "b": 2}
        else:
            reg = ServerRegistration(
                name=downstream_name,
                url=downstream_url,
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
                url=downstream_url,
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
                    server_url=downstream_url,
                    tool_name=first_tool,
                    arguments=tool_args,
                    transport=downstream_name,
                    command=cmd,
                    args=args,
                    auth_headers=auth_headers,
                )

                success = result.get("success", False)
                print(f"    Tool '{first_tool}': {'✓' if success else '✗'}")
                results.append((transport, downstream_name, success))
            else:
                print(f"    No tools discovered")
                results.append((transport, downstream_name, False))

        except Exception as e:
            print(f"    Error: {e}")
            results.append((transport, downstream_name, False))

    return results


@pytest.mark.skip(
    reason="Requires running MCP server - run manually for integration testing"
)
async def test_call_remote_tool():
    """Test the call_remote_tool orchestrator tool."""
    print("\n[5] Testing call_remote_tool Orchestrator Tool")

    from mcp_orchestrator.storage.memory import InMemoryStorage
    from mcp_orchestrator.server.registry import ServerRegistry
    from mcp_orchestrator.tools.search import ToolSearchService
    from mcp_orchestrator.mcp_server import MCPOrchestratorServer
    from mcp_orchestrator.models import ServerRegistration, AuthConfig

    results = []

    for transport in ["http", "stdio"]:
        print(f"\n  Orchestrator: {transport}")

        storage = InMemoryStorage()
        registry = ServerRegistry(storage)
        tool_search = ToolSearchService()

        server = MCPOrchestratorServer(
            storage=storage,
            server_registry=registry,
            tool_search=tool_search,
            auth_mode="auto",
            transport=transport,
        )

        # Register HTTP server
        reg = ServerRegistration(
            name="sample-http",
            url="http://127.0.0.1:8000/mcp",
            transport="http",
            auth=AuthConfig(
                type="static", headers={"Authorization": "Bearer sample-server-key"}
            ),
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
                results.append((transport, success))

        except Exception as e:
            print(f"    Error: {e}")
            results.append((transport, False))

    return results


async def main():
    print("=" * 60)
    print("MCP Orchestrator Tool Call Validation")
    print("=" * 60)

    # Test direct connections
    http_ok = await test_http_server()
    stdio_ok = await test_stdio_server()

    # Test router
    router_results = await test_router()

    # Test orchestrator transports
    orchestrator_results = await test_transports()

    # Test call_remote_tool
    call_results = await test_call_remote_tool()

    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    print("\n[Direct Server Connections]")
    print(f"  HTTP (8000/mcp):    {'✓ PASS' if http_ok else '✗ FAIL'}")
    print(f"  STDIO (subprocess): {'✓ PASS' if stdio_ok else '✗ FAIL'}")

    print("\n[ToolRouter Direct]")
    for transport, success in router_results:
        print(f"  {transport}: {'✓ PASS' if success else '✗ FAIL'}")

    print("\n[Orchestrator Transport Combinations]")
    for gt, dt, success in orchestrator_results:
        print(f"  {gt} -> {dt}: {'✓ PASS' if success else '✗ FAIL'}")

    print("\n[call_remote_tool]")
    for gt, success in call_results:
        print(f"  {gt}: {'✓ PASS' if success else '✗ FAIL'}")

    # Calculate totals
    all_tests = [http_ok, stdio_ok]
    all_tests.extend([s for _, s in router_results])
    all_tests.extend([s for _, _, s in orchestrator_results])
    all_tests.extend([s for _, s in call_results])

    passed = sum(1 for s in all_tests if s)
    total = len(all_tests)

    print(f"\n[TOTAL] {passed}/{total} tests passed ({100 * passed // total}%)")


if __name__ == "__main__":
    asyncio.run(main())
