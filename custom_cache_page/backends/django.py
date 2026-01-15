from __future__ import annotations

from typing import Any, Optional

from django.core.cache import caches
from django.http import HttpResponse

from ..indexes import BaseSurrogateIndex, DjangoCacheIndex
from .base import BaseCacheBackend, CacheEntry


class DjangoCacheBackend(BaseCacheBackend):
    """
    Backend using Django's cache framework.

    Options:
        cache_name: Django cache alias (default: "default")
        surrogate_index: Custom BaseSurrogateIndex instance for tracking
            surrogate keys. If not provided, uses DjangoCacheIndex.
            For high-concurrency production, use RedisSurrogateIndex.
        surrogate_index_timeout: TTL for surrogate index (default: 86400)

    Example with Redis surrogate index:
        from custom_cache_page.indexes import RedisSurrogateIndex

        backend = DjangoCacheBackend(
            cache_name="default",
            surrogate_index=RedisSurrogateIndex(url="redis://localhost:6379/0"),
        )
    """

    def __init__(
        self,
        cache_name: str = "default",
        surrogate_index: BaseSurrogateIndex | None = None,
        **options: Any,
    ) -> None:
        super().__init__(**options)
        self.cache_name = cache_name
        self._surrogate_index = surrogate_index
        self._surrogate_index_timeout: int = options.get(
            "surrogate_index_timeout", 86400
        )

    @property
    def cache(self):
        return caches[self.cache_name]

    @property
    def surrogate_index(self) -> BaseSurrogateIndex:
        if self._surrogate_index is None:
            self._surrogate_index = DjangoCacheIndex(
                cache=self.cache,
                timeout=self._surrogate_index_timeout,
            )
        return self._surrogate_index

    def get(self, key: str) -> Optional[HttpResponse]:
        cached = self.cache.get(key)
        if cached is None:
            return None

        response = HttpResponse(
            content=cached["content"],
            status=cached["status_code"],
            content_type=cached.get("content_type", "text/html"),
        )
        for header, value in cached.get("headers", {}).items():
            response[header] = value
        return response

    def set(self, entry: CacheEntry) -> None:
        response = entry.response
        headers = {}
        for header in ["Cache-Control", "Expires", "ETag", "Last-Modified", "Vary"]:
            if header in response:
                headers[header] = response[header]

        serialized = {
            "content": response.content.decode("utf-8"),
            "content_type": response.get("Content-Type", "text/html"),
            "status_code": response.status_code,
            "headers": headers,
        }
        self.cache.set(entry.key, serialized, entry.timeout)
        for surrogate in entry.surrogate_keys:
            self.surrogate_index.add(surrogate, entry.key)

    def delete(self, key: str) -> bool:
        return self.cache.delete(key)

    def invalidate_by_surrogate(self, surrogate_key: str) -> int:
        keys = self.surrogate_index.get_keys(surrogate_key)
        if not keys:
            return 0

        count = 0
        for key in keys:
            if self.cache.delete(key):
                count += 1

        self.surrogate_index.remove(surrogate_key)
        return count

    def get_group_version(self, group: str, timeout: int) -> int:
        return self.cache.get_or_set(group, 1, timeout=timeout)

    def increment_group_version(self, group: str) -> int:
        try:
            return self.cache.incr(group)
        except ValueError:
            self.cache.set(group, 2)
            return 2
