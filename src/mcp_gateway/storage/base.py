"""Storage backends for MCP Gateway."""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import json


class StorageBackend(ABC):
    """Abstract storage interface."""
    
    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get value by key."""
        pass
    
    @abstractmethod
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value by key with optional TTL."""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete value by key. Returns True if deleted."""
        pass
    
    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        pass
    
    @abstractmethod
    async def keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching pattern."""
        pass
    
    @abstractmethod
    async def hget(self, key: str, field: str) -> Optional[Any]:
        """Get hash field value."""
        pass
    
    @abstractmethod
    async def hset(self, key: str, field: str, value: Any) -> None:
        """Set hash field value."""
        pass
    
    @abstractmethod
    async def hgetall(self, key: str) -> Dict[str, Any]:
        """Get all hash fields and values."""
        pass
    
    @abstractmethod
    async def hdel(self, key: str, field: str) -> bool:
        """Delete hash field. Returns True if deleted."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close storage connection."""
        pass
