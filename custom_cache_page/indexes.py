from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseSurrogateIndex(ABC):
    """
    Abstract interface for surrogate key indexing.

    A surrogate index maps surrogate keys to cache keys, enabling
    bulk invalidation of related cache entries.
    """

    @abstractmethod
    def add(self, surrogate_key: str, cache_key: str) -> None:
        """Add a cache key to a surrogate key's index."""

    @abstractmethod
    def get_keys(self, surrogate_key: str) -> set[str]:
        """Get all cache keys associated with a surrogate key."""

    @abstractmethod
    def remove(self, surrogate_key: str) -> None:
        """Remove a surrogate key's entire index."""


class DjangoCacheIndex(BaseSurrogateIndex):
    """
    Surrogate index using Django's cache framework.

    Automatically detects Redis-backed caches and uses native SADD.
    Applies Django cache KEY_PREFIX when using Redis directly.
    """

    def __init__(self, cache: Any, timeout: int = 86400, prefix: str = "_surrogate:"):
        self.cache = cache
        self.timeout = timeout
        self.prefix = prefix
        self._redis_client = self._get_redis_client()
        self._cache_prefix = self._get_cache_prefix() if self._redis_client else ""

    def _get_redis_client(self) -> Any:
        """Try to get native Redis client from Django cache backend."""
        try:
            client = getattr(self.cache, "_cache", None)
            if client is None:
                client = getattr(self.cache, "client", None)
            if client is not None:
                get_client = getattr(client, "get_client", None)
                if get_client:
                    redis_client = get_client()
                    if hasattr(redis_client, "sadd") and hasattr(
                        redis_client, "smembers"
                    ):
                        return redis_client
        except Exception:
            pass
        return None

    def _get_cache_prefix(self) -> str:
        """Get Django cache KEY_PREFIX for use with direct Redis access."""
        try:
            key_prefix = getattr(self.cache, "key_prefix", None)
            if key_prefix:
                return key_prefix
            client = getattr(self.cache, "_cache", None)
            if client is not None:
                return getattr(client, "_prefix", "") or ""
        except Exception:
            pass
        return ""

    def _index_key(self, surrogate_key: str) -> str:
        if self._redis_client and self._cache_prefix:
            return f"{self._cache_prefix}{self.prefix}{surrogate_key}"
        return f"{self.prefix}{surrogate_key}"

    def add(self, surrogate_key: str, cache_key: str) -> None:
        index_key = self._index_key(surrogate_key)
        if self._redis_client:
            pipe = self._redis_client.pipeline()
            pipe.sadd(index_key, cache_key)
            pipe.expire(index_key, self.timeout)
            pipe.execute()
        else:
            keys: list[str] = self.cache.get(index_key, [])
            if cache_key not in keys:
                keys.append(cache_key)
            self.cache.set(index_key, keys, self.timeout)

    def get_keys(self, surrogate_key: str) -> set[str]:
        index_key = self._index_key(surrogate_key)
        if self._redis_client:
            members = self._redis_client.smembers(index_key)
            return {m.decode() if isinstance(m, bytes) else m for m in members}
        return set(self.cache.get(index_key, []))

    def remove(self, surrogate_key: str) -> None:
        index_key = self._index_key(surrogate_key)
        if self._redis_client:
            self._redis_client.delete(index_key)
        else:
            self.cache.delete(index_key)


class RedisSurrogateIndex(BaseSurrogateIndex):
    """
    Surrogate index using native Redis sets.

    Requires redis-py: pip install django-custom-cache-page[redis]
    """

    def __init__(
        self,
        redis_client: Any = None,
        url: str | None = None,
        timeout: int = 86400,
        prefix: str = "_surrogate:",
    ):
        self.timeout = timeout
        self.prefix = prefix

        if redis_client is not None:
            self.redis = redis_client
        elif url:
            self.redis = self._create_client(url)
        else:
            raise ValueError("Either redis_client or url must be provided")

    def _create_client(self, url: str) -> Any:
        try:
            import redis  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "redis-py is required for RedisSurrogateIndex. "
                "Install with: pip install redis"
            ) from e
        return redis.from_url(url)

    def _index_key(self, surrogate_key: str) -> str:
        return f"{self.prefix}{surrogate_key}"

    def add(self, surrogate_key: str, cache_key: str) -> None:
        key = self._index_key(surrogate_key)
        pipe = self.redis.pipeline()
        pipe.sadd(key, cache_key)
        pipe.expire(key, self.timeout)
        pipe.execute()

    def get_keys(self, surrogate_key: str) -> set[str]:
        members = self.redis.smembers(self._index_key(surrogate_key))
        return {m.decode() if isinstance(m, bytes) else m for m in members}

    def remove(self, surrogate_key: str) -> None:
        self.redis.delete(self._index_key(surrogate_key))


class NullSurrogateIndex(BaseSurrogateIndex):
    """
    No-op surrogate index.

    Use when surrogate key tracking is not needed (e.g., CDN-only caching
    where invalidation happens via API, not local index).
    """

    def add(self, surrogate_key: str, cache_key: str) -> None:
        pass

    def get_keys(self, surrogate_key: str) -> set[str]:
        return set()

    def remove(self, surrogate_key: str) -> None:
        pass
