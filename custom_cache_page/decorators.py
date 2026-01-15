from dataclasses import dataclass
from functools import wraps
from typing import Callable, Optional, Union

from django.http import HttpRequest, HttpResponse
from django.utils.cache import patch_response_headers

from .backends.base import BaseCacheBackend, CacheEntry
from .conf import get_backend_by_name, get_default_backend
from .keys import hash_key
from .surrogates import SurrogateKeySet

KeyFuncType = Callable[[HttpRequest], str]
TimeoutType = Union[int, Callable[[HttpResponse], int]]
PrefixType = Union[str, Callable[[HttpRequest], str], None]
VersionedNameType = Union[str, Callable[[HttpRequest], str]]
TagType = Union[str, Callable[[HttpRequest], Union[str, list[str], None]], "Versioned"]
TagsType = Optional[list[TagType]]


@dataclass
class Versioned:
    """
    Wrap a tag name to enable O(1) versioned invalidation.

    When a versioned tag is invalidated, instead of deleting all cached entries,
    the version number is incremented. This makes invalidation O(1) regardless
    of how many entries exist.

    The name can be a static string or a callable that returns a string.

    Example:
        @cache_page(
            timeout=3600,
            key_func=lambda r: r.path,
            tags=[
                versioned("products"),
                versioned(lambda r: f"store:{r.store.id}"),
            ],
        )
    """

    name: VersionedNameType
    timeout: int = 864000

    def resolve_name(self, request: HttpRequest) -> str:
        if callable(self.name):
            return self.name(request)
        return self.name


def versioned(
    name: VersionedNameType,
    timeout: int = 864000,
) -> Versioned:
    """
    Create a versioned tag for O(1) cache invalidation.

    Args:
        name: Tag name (string or callable returning string)
        timeout: TTL for the version key (default: 10 days)

    Example:
        tags=[
            versioned("products"),
            versioned(lambda r: f"store:{r.store.id}"),
        ]
    """
    return Versioned(name=name, timeout=timeout)


def cache_page(
    timeout: TimeoutType,
    key_func: KeyFuncType,
    *,
    tags: TagsType = None,
    prefix: PrefixType = None,
    backend: Optional[Union[BaseCacheBackend, str]] = None,
    cache_name: str = "default",
    only_if: Optional[Callable[[HttpRequest], bool]] = None,
) -> Callable:
    """
    Cache page decorator with surrogate-key and versioned tag support.

    Args:
        timeout: Cache timeout in seconds (int or callable returning int from response)
        key_func: Function to generate cache key from request
        tags: Cache tags for invalidation (strings, callables, or versioned())
        prefix: Cache key prefix (string or callable returning string)
        backend: Cache backend (None=default, str=name, or instance)
        cache_name: Django cache name for default backend
        only_if: Condition function; if returns False, bypass cache

    Example:
        @cache_page(
            timeout=3600,
            key_func=lambda r: r.path,
            prefix=lambda r: f"store:{r.store.id}",
            tags=[versioned("products")],
        )
        def product_list(request):
            return HttpResponse(...)
    """

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            # Check if caching should be bypassed
            if getattr(request, "do_not_cache", False):
                return view_func(request, *args, **kwargs)

            if only_if is not None and not only_if(request):
                return view_func(request, *args, **kwargs)

            # Resolve backend
            resolved_backend = _resolve_backend(backend, cache_name)

            # Resolve tags and extract versioned ones
            resolved_tags, versioned_tags = _resolve_tags(request, tags)

            # Build cache key (includes version numbers for versioned tags)
            cache_key = _build_cache_key(
                request=request,
                key_func=key_func,
                prefix=prefix,
                versioned_tags=versioned_tags,
                backend=resolved_backend,
            )

            # Try to get cached response
            cached_response = resolved_backend.get(cache_key)
            bust_cache = getattr(request, "_bust_cache", False)

            if cached_response is not None and not bust_cache:
                return cached_response

            # Generate response
            response = view_func(request, *args, **kwargs)

            # Only cache successful responses
            if response.status_code != 200:
                return response

            # Handle TemplateResponse (deferred rendering)
            if hasattr(response, "render") and callable(response.render):

                def post_render_callback(rendered_response):
                    resolved_timeout = timeout(rendered_response) if callable(timeout) else timeout
                    patch_response_headers(rendered_response, resolved_timeout)
                    final_response = resolved_backend.prepare_response(
                        rendered_response,
                        resolved_tags.keys,
                    )
                    entry = CacheEntry(
                        key=cache_key,
                        response=final_response,
                        timeout=resolved_timeout,
                        surrogate_keys=resolved_tags.keys,
                    )
                    resolved_backend.set(entry)

                response.add_post_render_callback(post_render_callback)
            else:
                resolved_timeout = timeout(response) if callable(timeout) else timeout
                patch_response_headers(response, resolved_timeout)
                response = resolved_backend.prepare_response(
                    response,
                    resolved_tags.keys,
                )
                entry = CacheEntry(
                    key=cache_key,
                    response=response,
                    timeout=resolved_timeout,
                    surrogate_keys=resolved_tags.keys,
                )
                resolved_backend.set(entry)

            setattr(request, "_cache_update_cache", False)
            return response

        return wrapper

    return decorator


def _resolve_backend(
    backend: Optional[Union[BaseCacheBackend, str]],
    cache_name: str,
) -> BaseCacheBackend:
    """Resolve backend specification to actual backend instance."""
    if backend is None:
        return get_default_backend(cache_name=cache_name)

    if isinstance(backend, str):
        return get_backend_by_name(backend)

    return backend


def _resolve_tags(
    request: HttpRequest,
    tags: TagsType,
) -> tuple[SurrogateKeySet, list[Versioned]]:
    """
    Resolve tags to SurrogateKeySet and list of Versioned tags.

    Returns:
        (resolved_tags, versioned_tags)
    """
    result = SurrogateKeySet()
    versioned_list: list[Versioned] = []

    if tags is None:
        return result, versioned_list

    for item in tags:
        if isinstance(item, Versioned):
            versioned_list.append(item)
            result.add(item.resolve_name(request))
        elif isinstance(item, str):
            result.add(item)
        elif callable(item):
            keys = item(request)
            if isinstance(keys, str):
                result.add(keys)
            elif keys:
                result.add(*keys)

    return result, versioned_list


def _build_cache_key(
    request: HttpRequest,
    key_func: KeyFuncType,
    prefix: PrefixType,
    versioned_tags: list[Versioned],
    backend: BaseCacheBackend,
) -> str:
    """Build the full cache key, including version numbers for versioned tags."""
    version_parts = []
    for vtag in versioned_tags:
        tag_name = vtag.resolve_name(request)
        version = backend.get_group_version(tag_name, vtag.timeout)
        version_parts.append(f"{tag_name}:{version}")

    resolved_prefix = prefix(request) if callable(prefix) else prefix
    version_str = ",".join(version_parts) if version_parts else ""
    raw_key = f"{resolved_prefix}:{version_str}:{key_func(request)}"
    return hash_key(raw_key)


def invalidate_tag(tag: str, backend: Optional[str] = None) -> int:
    """
    Invalidate all caches with the given tag.

    For versioned tags: O(1) via version increment
    For regular tags: Deletes all entries with the tag

    Args:
        tag: The tag to invalidate
        backend: Optional backend name (uses default if not specified)

    Returns:
        Number of entries invalidated (or new version for versioned tags)
    """
    b = get_backend_by_name(backend) if backend else get_default_backend()

    # Try versioned invalidation first (O(1))
    try:
        return b.increment_group_version(tag)
    except (NotImplementedError, ValueError):
        pass

    # Fall back to surrogate key invalidation
    return b.invalidate_by_surrogate(tag)


def invalidate_tags(tags: list[str], backend: Optional[str] = None) -> int:
    """
    Invalidate all caches with any of the given tags.

    Args:
        tags: List of tags to invalidate
        backend: Optional backend name (uses default if not specified)

    Returns:
        Total number of entries invalidated
    """
    b = get_backend_by_name(backend) if backend else get_default_backend()

    total = 0
    for tag in tags:
        try:
            total += b.increment_group_version(tag)
        except (NotImplementedError, ValueError):
            total += b.invalidate_by_surrogate(tag)

    return total
