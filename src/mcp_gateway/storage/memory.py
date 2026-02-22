"""In-memory storage backend."""

import time
from typing import Optional, Dict, Any, List
from .base import StorageBackend


class InMemoryStorage(StorageBackend):
    """In-memory storage backend with TTL support."""
    
    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._expires: Dict[str, float] = {}
        self._hashes: Dict[str, Dict[str, Any]] = {}
    
    def _is_expired(self, key: str) -> bool:
        """Check if key is expired."""
        if key in self._expires:
            if time.time() > self._expires[key]:
                self._data.pop(key, None)
                self._expires.pop(key, None)
                return True
        return False
    
    def _cleanup_expired(self):
        """Remove all expired keys."""
        current_time = time.time()
        expired = [
            key for key, exp in self._expires.items()
            if current_time > exp
        ]
        for key in expired:
            self._data.pop(key, None)
            self._expires.pop(key, None)
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value by key."""
        if self._is_expired(key):
            return None
        return self._data.get(key)
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value by key with optional TTL."""
        self._data[key] = value
        if ttl:
            self._expires[key] = time.time() + ttl
        else:
            self._expires.pop(key, None)
    
    async def delete(self, key: str) -> bool:
        """Delete value by key."""
        if key in self._data:
            del self._data[key]
            self._expires.pop(key, None)
            return True
        return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        if self._is_expired(key):
            return False
        return key in self._data
    
    async def keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching pattern."""
        self._cleanup_expired()
        if pattern == "*":
            return list(self._data.keys())
        
        import fnmatch
        return [k for k in self._data.keys() if fnmatch.fnmatch(k, pattern)]
    
    async def hget(self, key: str, field: str) -> Optional[Any]:
        """Get hash field value."""
        if key in self._hashes:
            return self._hashes[key].get(field)
        return None
    
    async def hset(self, key: str, field: str, value: Any) -> None:
        """Set hash field value."""
        if key not in self._hashes:
            self._hashes[key] = {}
        self._hashes[key][field] = value
    
    async def hgetall(self, key: str) -> Dict[str, Any]:
        """Get all hash fields and values."""
        return self._hashes.get(key, {}).copy()
    
    async def hdel(self, key: str, field: str) -> bool:
        """Delete hash field."""
        if key in self._hashes and field in self._hashes[key]:
            del self._hashes[key][field]
            return True
        return False
    
    async def close(self) -> None:
        """Close storage (no-op for memory)."""
        self._data.clear()
        self._expires.clear()
        self._hashes.clear()
