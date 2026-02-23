# Contributing to MCP Gateway

Thank you for your interest in contributing! This project welcomes contributions from the community.

## Getting Started

```bash
# Clone the repository
git clone https://github.com/rupinder2/mcp-gateway.git
cd mcp-gateway

# Install dependencies with uv
uv sync --dev

# Run tests
uv run pytest
```

## Development Setup

### Environment Configuration

Copy `.env.example` to `.env` and configure as needed:

```bash
cp .env.example .env
```

### Running Locally

```bash
# Run as stdio MCP server
python -m mcp_gateway.main

# Or with HTTP transport
GATEWAY_TRANSPORT=http GATEWAY_PORT=8080 python -m mcp_gateway.main
```

### Testing with MCP Inspector

```bash
mcp dev src/mcp_gateway/main.py
```

## How to Contribute

### Bug Fixes

1. **Open an issue first** - Describe the bug and expected behavior
2. **Reference the issue** in your PR description
3. **Write tests** that demonstrate the bug is fixed

### New Storage Backends

1. Implement the `StorageBackend` interface from `src/mcp_gateway/storage/base.py`
2. Add configuration handling in the storage module
3. Include comprehensive tests (success and error paths)
4. Update documentation

### New Transport Types

- **Discuss in an issue first** before building
- Consider backward compatibility and existing patterns
- Document the new transport in the README

### Documentation

- Always welcome - no issue needed
- Follow existing documentation style
- Keep code snippets working and accurate

## PR Guidelines

- All tests must pass before merging
- Follow existing code style (type hints throughout)
- One feature or fix per PR
- Update `docs/codebase.md` for significant architecture changes

## Code Style

- **Dependency manager**: [uv](https://github.com/astral-sh/uv)
- **Type hints**: Required on all function signatures
- **Error handling**: Use `logger.exception` for unexpected errors, `logger.error` for expected failures
- **Responses**: Use structured responses with `success` flag

## Questions?

Open a discussion at https://github.com/rupinder2/mcp-gateway/discussions
