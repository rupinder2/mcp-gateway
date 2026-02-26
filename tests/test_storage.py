"""Tests for storage backends."""

import pytest
import asyncio
from mcp_orchestrator.storage.memory import InMemoryStorage
from mcp_orchestrator.storage.base import StorageBackend


@pytest.fixture
async def memory_storage():
    """Create in-memory storage for testing."""
    return InMemoryStorage()


@pytest.mark.asyncio
async def test_memory_storage_get_set(memory_storage):
    """Test basic get/set operations."""
    await memory_storage.set("key1", "value1")
    result = await memory_storage.get("key1")
    assert result == "value1"


@pytest.mark.asyncio
async def test_memory_storage_get_nonexistent(memory_storage):
    """Test getting non-existent key."""
    result = await memory_storage.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_memory_storage_delete(memory_storage):
    """Test delete operation."""
    await memory_storage.set("key1", "value1")
    
    # Delete should return True
    result = await memory_storage.delete("key1")
    assert result is True
    
    # Key should be gone
    value = await memory_storage.get("key1")
    assert value is None
    
    # Delete non-existent should return False
    result = await memory_storage.delete("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_memory_storage_exists(memory_storage):
    """Test exists operation."""
    await memory_storage.set("key1", "value1")
    
    assert await memory_storage.exists("key1") is True
    assert await memory_storage.exists("nonexistent") is False


@pytest.mark.asyncio
async def test_memory_storage_keys(memory_storage):
    """Test keys operation."""
    await memory_storage.set("key1", "value1")
    await memory_storage.set("key2", "value2")
    await memory_storage.set("other", "value3")
    
    # Get all keys
    keys = await memory_storage.keys("*")
    assert len(keys) == 3
    assert "key1" in keys
    assert "key2" in keys
    assert "other" in keys
    
    # Get keys with pattern
    keys = await memory_storage.keys("key*")
    assert len(keys) == 2
    assert "key1" in keys
    assert "key2" in keys


@pytest.mark.asyncio
async def test_memory_storage_hash_operations(memory_storage):
    """Test hash operations."""
    # Set hash fields
    await memory_storage.hset("hash1", "field1", "value1")
    await memory_storage.hset("hash1", "field2", "value2")
    
    # Get single field
    value = await memory_storage.hget("hash1", "field1")
    assert value == "value1"
    
    # Get non-existent field
    value = await memory_storage.hget("hash1", "nonexistent")
    assert value is None
    
    # Get all fields
    all_fields = await memory_storage.hgetall("hash1")
    assert all_fields == {"field1": "value1", "field2": "value2"}
    
    # Delete field
    result = await memory_storage.hdel("hash1", "field1")
    assert result is True
    
    # Verify deletion
    value = await memory_storage.hget("hash1", "field1")
    assert value is None
    
    # Delete non-existent field
    result = await memory_storage.hdel("hash1", "nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_memory_storage_ttl():
    """Test TTL functionality."""
    storage = InMemoryStorage()
    
    # Set with short TTL
    await storage.set("key1", "value1", ttl=1)
    
    # Should exist immediately
    assert await storage.exists("key1") is True
    
    # Wait for expiration
    await asyncio.sleep(1.5)
    
    # Should be expired
    assert await storage.exists("key1") is False
    assert await storage.get("key1") is None


@pytest.mark.asyncio
async def test_memory_storage_close(memory_storage):
    """Test close operation clears all data."""
    await memory_storage.set("key1", "value1")
    await memory_storage.hset("hash1", "field1", "value1")
    
    await memory_storage.close()
    
    # All data should be cleared
    assert await memory_storage.get("key1") is None
    assert await memory_storage.hget("hash1", "field1") is None
    assert len(await memory_storage.keys("*")) == 0


@pytest.mark.asyncio
async def test_storage_with_complex_values(memory_storage):
    """Test storage with complex Python objects."""
    complex_value = {
        "name": "test",
        "items": [1, 2, 3],
        "nested": {"a": 1, "b": 2}
    }
    
    await memory_storage.set("complex", complex_value)
    result = await memory_storage.get("complex")
    
    assert result == complex_value
