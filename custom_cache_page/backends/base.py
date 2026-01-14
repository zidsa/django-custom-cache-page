from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from django.http import HttpResponse


@dataclass
class CacheEntry:
    """Represents a cached response with metadata."""

    key: str
    response: HttpResponse
    timeout: int
    surrogate_keys: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseCacheBackend(ABC):
    """
    Abstract base class for cache backends.

    All backends must implement get, set, delete, and invalidate_by_surrogate.
    """

    def __init__(self, **options: Any) -> None:
        self.options = options

    @abstractmethod
    def get(self, key: str) -> Optional[HttpResponse]:
        """
        Retrieve a cached response by key.

        Args:
            key: The cache key

        Returns:
            The cached HttpResponse or None if not found
        """

    @abstractmethod
    def set(self, entry: CacheEntry) -> None:
        """
        Store a response in the cache.

        Args:
            entry: CacheEntry containing key, response, timeout, and surrogate keys
        """

    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        Delete a single cache entry by key.

        Args:
            key: The cache key to delete

        Returns:
            True if deleted, False if not found
        """

    @abstractmethod
    def invalidate_by_surrogate(self, surrogate_key: str) -> int:
        """
        Invalidate all cache entries tagged with the given surrogate key.

        Args:
            surrogate_key: The surrogate key to invalidate

        Returns:
            Number of entries invalidated (may be approximate for CDNs)
        """

    def invalidate_by_surrogates(self, surrogate_keys: list[str]) -> int:
        """
        Invalidate all cache entries tagged with any of the given surrogate keys.

        Default implementation calls invalidate_by_surrogate for each key.
        Backends may override for batch operations.
        """
        total = 0
        for key in surrogate_keys:
            total += self.invalidate_by_surrogate(key)
        return total

    def prepare_response(
        self,
        response: HttpResponse,
        surrogate_keys: list[str],
    ) -> HttpResponse:
        """
        Prepare the response before sending to client.

        Override this to add CDN-specific headers.
        Default implementation does nothing.
        """
        return response

    def get_group_version(self, group: str, timeout: int) -> int:
        """Get or create version number for a group."""
        raise NotImplementedError("Group versioning not supported by this backend")

    def increment_group_version(self, group: str) -> int:
        """Increment version for a group (invalidates all entries in group)."""
        raise NotImplementedError("Group versioning not supported by this backend")


class HeaderAwareMixin:
    """Mixin for backends that add surrogate key headers to responses."""

    SURROGATE_KEY_HEADER = "Surrogate-Key"
    MAX_HEADER_SIZE = 16 * 1024  # 16KB
    MAX_KEY_SIZE = 1024  # 1KB per key

    def add_surrogate_headers(
        self,
        response: HttpResponse,
        surrogate_keys: list[str],
    ) -> HttpResponse:
        """Add Surrogate-Key header to response."""
        if not surrogate_keys:
            return response

        valid_keys = []
        total_size = 0

        for key in surrogate_keys:
            key_size = len(key.encode("utf-8"))
            if key_size > self.MAX_KEY_SIZE:
                continue
            if total_size + key_size + 1 > self.MAX_HEADER_SIZE:
                break
            valid_keys.append(key)
            total_size += key_size + 1

        if valid_keys:
            response[self.SURROGATE_KEY_HEADER] = " ".join(valid_keys)

        return response
