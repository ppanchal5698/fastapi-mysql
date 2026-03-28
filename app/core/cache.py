import asyncio
import functools
import hashlib
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any, cast

import redis.asyncio as aioredis
from loguru import logger
from redis.asyncio.connection import ConnectionPool

_CACHE_MISS = object()

_pool: ConnectionPool | None = None


async def init_redis_pool(
    host: str,
    port: int = 6379,
    db: int = 0,
    password: str | None = None,
    max_connections: int = 50,
) -> ConnectionPool:
    """
    Called once at app startup (inside lifespan).
    max_connections=50 handles ~500 concurrent requests
    (each holds the connection for ~10ms avg).
    """
    global _pool
    _pool = ConnectionPool(
        host=host,
        port=port,
        db=db,
        password=password,
        max_connections=max_connections,
        decode_responses=True,
        socket_timeout=5.0,
        socket_connect_timeout=3.0,
        socket_keepalive=True,
        retry_on_timeout=True,
        health_check_interval=30,
    )
    client = aioredis.Redis(connection_pool=_pool)
    await cast(Awaitable[bool], client.ping())
    await client.aclose()
    logger.info(
        "Redis pool initialized | host={}:{} | max_conn={}",
        host,
        port,
        max_connections,
    )
    return _pool


async def close_redis_pool() -> None:
    global _pool
    if _pool:
        await _pool.disconnect()
        logger.info("Redis pool closed")


async def get_cache() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency — yields a Redis client from the shared pool."""
    if _pool is None:
        raise RuntimeError("Redis pool not initialized. Call init_redis_pool() in lifespan.")
    client = aioredis.Redis(connection_pool=_pool)
    try:
        yield client
    finally:
        await client.aclose()


_SERIALIZABLE_TYPES = (str, int, float, bool, type(None), list, tuple, dict)


class RedisCache:
    """
    High-level cache interface with serialization and namespacing.
    Patterns:
      - Cache-Aside  : get -> miss -> fetch DB -> set
      - Write-Through: write DB -> immediately invalidate/update cache
    """

    def __init__(self, client: aioredis.Redis, namespace: str = "app"):
        self.client = client
        self.namespace = namespace

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    async def get(self, key: str) -> Any:
        """
        Returns deserialized value, or _CACHE_MISS sentinel if key does not exist.
        Callers should compare with ``_CACHE_MISS`` — never rely on None checks.
        """
        raw = await self.client.get(self._key(key))
        if raw is None:
            return _CACHE_MISS
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """TTL in seconds. Default 5 minutes."""
        serialized = json.dumps(value, default=str)
        await self.client.setex(self._key(key), ttl, serialized)

    async def delete(self, key: str) -> None:
        await self.client.delete(self._key(key))

    async def delete_pattern(self, pattern: str) -> int:
        """Invalidate all keys matching a glob pattern (e.g. 'user:*')."""
        count = 0
        async for key in self.client.scan_iter(match=self._key(pattern), count=100):
            await self.client.delete(key)
            count += 1
        return count

    async def exists(self, key: str) -> bool:
        return bool(await self.client.exists(self._key(key)))

    async def increment(self, key: str, amount: int = 1, ttl: int = 60) -> int:
        """Atomic counter — useful for rate tracking or feature flags."""
        full_key = self._key(key)
        count: int = await self.client.incrby(full_key, amount)
        if count == amount:
            await self.client.expire(full_key, ttl)
        return count

    async def get_or_set(
        self,
        key: str,
        fetcher: Callable[[], Any] | Callable[[], Awaitable[Any]],
        ttl: int = 300,
    ) -> Any:
        """
        Cache-Aside pattern in one call.
        Usage: data = await cache.get_or_set("user:42", lambda: fetch_user(42), ttl=600)
        """
        cached = await self.get(key)
        if cached is not _CACHE_MISS:
            logger.debug("Cache HIT | key={}", key)
            return cached
        logger.debug("Cache MISS | key={}", key)
        if asyncio.iscoroutinefunction(fetcher):
            value = await fetcher()
        else:
            value = fetcher()
        await self.set(key, value, ttl)
        return value


def _build_cache_key(func_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """
    Build a deterministic cache key from only JSON-serializable arguments,
    filtering out FastAPI dependency-injected objects (Redis clients, sessions, etc.).
    """
    safe_args = [a for a in args if isinstance(a, _SERIALIZABLE_TYPES)]
    safe_kwargs = {
        k: v for k, v in sorted(kwargs.items())
        if isinstance(v, _SERIALIZABLE_TYPES)
    }
    key_data = json.dumps({"fn": func_name, "a": safe_args, "kw": safe_kwargs}, sort_keys=True, default=str)
    return hashlib.md5(key_data.encode(), usedforsecurity=False).hexdigest()


def cache_response(ttl: int = 300, namespace: str = "route"):
    """
    Decorator for FastAPI route functions.
    Caches the JSON response keyed by function name + serializable args hash.

    Usage:
        @router.get("/users/{user_id}")
        @cache_response(ttl=600, namespace="users")
        async def get_user(user_id: int, cache: Redis = Depends(get_cache)):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache_client = kwargs.get("cache") if "cache" in kwargs else kwargs.get("redis")
            if cache_client is None:
                return await func(*args, **kwargs)

            rc = RedisCache(cache_client, namespace)
            cache_key = _build_cache_key(func.__name__, args, kwargs)

            cached = await rc.get(cache_key)
            if cached is not _CACHE_MISS:
                return cached

            result = await func(*args, **kwargs)
            await rc.set(cache_key, result, ttl)
            return result

        return wrapper

    return decorator
