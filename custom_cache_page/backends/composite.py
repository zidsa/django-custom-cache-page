from typing import Any, Optional

from django.http import HttpResponse

from .base import BaseCacheBackend, CacheEntry


class CompositeBackend(BaseCacheBackend):
    """
    Backend that combines multiple backends.

    Use cases:
    - Store in Django cache AND send surrogate headers to CDN
    - Invalidate both local cache and CDN simultaneously

    Options:
        backends: List of BaseCacheBackend instances
        read_from: Index of backend to read from (default: 0, first backend)
    """

    def __init__(self, backends: list[BaseCacheBackend], **options: Any) -> None:
        super().__init__(**options)
        self.backends = backends
        self.read_from: int = options.get("read_from", 0)

    def get(self, key: str) -> Optional[HttpResponse]:
        """Get from primary read backend."""
        if 0 <= self.read_from < len(self.backends):
            return self.backends[self.read_from].get(key)
        return None

    def set(self, entry: CacheEntry) -> None:
        """Store in all backends."""
        for backend in self.backends:
            backend.set(entry)

    def delete(self, key: str) -> bool:
        """Delete from all backends."""
        results = [backend.delete(key) for backend in self.backends]
        return any(results)

    def invalidate_by_surrogate(self, surrogate_key: str) -> int:
        """Invalidate in all backends."""
        total = 0
        for backend in self.backends:
            total += backend.invalidate_by_surrogate(surrogate_key)
        return total

    def invalidate_by_surrogates(self, surrogate_keys: list[str]) -> int:
        """Batch invalidate in all backends."""
        total = 0
        for backend in self.backends:
            total += backend.invalidate_by_surrogates(surrogate_keys)
        return total

    def prepare_response(
        self,
        response: HttpResponse,
        surrogate_keys: list[str],
    ) -> HttpResponse:
        """Let all backends prepare the response."""
        for backend in self.backends:
            response = backend.prepare_response(response, surrogate_keys)
        return response

    def get_group_version(self, group: str, timeout: int) -> int:
        """Get version from first backend that supports it."""
        for backend in self.backends:
            try:
                return backend.get_group_version(group, timeout)
            except NotImplementedError:
                continue
        raise NotImplementedError("No backend supports group versioning")

    def increment_group_version(self, group: str) -> int:
        """Increment version in all backends that support it."""
        version = None
        for backend in self.backends:
            try:
                v = backend.increment_group_version(group)
                if version is None:
                    version = v
            except NotImplementedError:
                continue

        if version is None:
            raise NotImplementedError("No backend supports group versioning")
        return version
