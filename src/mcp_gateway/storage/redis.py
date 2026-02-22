"""Redis storage backend."""

import json
from typing import Optional, Dict, Any, List
import redis.asyncio as redis
from .base import StorageBackend


class RedisStorage(StorageBackend):
    """Redis storage backend."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self._redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
    
    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = await redis.from_url(self._redis_url)
        return self._redis
    
    def _serialize(self, value: Any) -> str:
        """Serialize value to JSON string."""
        return json.dumps(value)
    
    def _deserialize(self, value: Optional[bytes]) -> Optional[Any]:
        """Deserialize JSON string to value."""
        if value is None:
            return None
        return json.loads(value)
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value by key."""
        r = await self._get_redis()
        value = await r.get(key)
        return self._deserialize(value)
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value by key with optional TTL."""
        r = await self._get_redis()
        serialized = self._serialize(value)
        if ttl:
            await r.setex(key, ttl, serialized)
        else:
            await r.set(key, serialized)
    
    async def delete(self, key: str) -> bool:
        """Delete value by key."""
        r = await self._get_redis()
        result = await r.delete(key)
        return result > 0
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        r = await self._get_redis()
        return await r.exists(key) > 0
    
    async def keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching pattern."""
        r = await self._get_redis()
        keys = await r.keys(pattern)
        return [k.decode() if isinstance(k, bytes) else k for k in keys]
    
    async def hget(self, key: str, field: str) -> Optional[Any]:
        """Get hash field value."""
        r = await self._get_redis()
        value = await r.hget(key, field)
        return self._deserialize(value)
    
    async def hset(self, key: str, field: str, value: Any) -> None:
        """Set hash field value."""
        r = await self._get_redis()
        await r.hset(key, field, self._serialize(value))
    
    async def hgetall(self, key: str) -> Dict[str, Any]:
        """Get all hash fields and values."""
        r = await self._get_redis()
        result = await r.hgetall(key)
        return {
            k.decode() if isinstance(k, bytes) else k: self._deserialize(v)
            for k, v in result.items()
        }
    
    async def hdel(self, key: str, field: str) -> bool:
        """Delete hash field."""
        r = await self._get_redis()
        result = await r.hdel(key, field)
        return result > 0
    
    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
