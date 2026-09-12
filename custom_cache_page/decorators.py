from dataclasses import dataclass
from functools import wraps
from typing import Callable, Optional, Union

from django.http import HttpRequest, HttpResponse

from .backends.base import BaseCacheBackend, CacheEntry
from .conf import get_backend_by_name, get_default_backend
from .http_cache import (
    forbid_cache,
    make_metadata,
    representation_key,
    request_allows_cache,
    request_requires_revalidation,
    response_allows_cache,
    snapshot_requires_rebuild,
    validate_cached_response,
)
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
    etag: Union[bool, Callable[[HttpRequest], bool]] = False,
    vary_on: tuple[str, ...] = (),
    max_age: Optional[int] = None,
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
        etag: Enable HTTP validation, or a per-request feature flag callable
        vary_on: Request headers that select distinct HTTP representations
        max_age: Optional outbound freshness cap; does not shorten storage timeout

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

    if max_age is not None and max_age < 0:
        raise ValueError("max_age must be nonnegative")

    def decorator(view_func: Callable) -> Callable:
        @wraps(view_func)
        def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            use_etag = etag(request) if callable(etag) else etag
            setattr(request, "_cache_page_status", "bypass")
            setattr(request, "_cache_page_key", None)
            if (
                getattr(request, "do_not_cache", False)
                or (only_if is not None and not only_if(request))
                or not request_allows_cache(request)
            ):
                response = view_func(request, *args, **kwargs)
                setattr(request, "_cache_update_cache", False)
                return forbid_cache(response)

            resolved_backend = _resolve_backend(backend, cache_name)
            resolved_tags, versioned_tags, indexed_tags = _resolve_tags(request, tags)
            cache_key = _build_cache_key(
                request=request,
                key_func=key_func,
                prefix=prefix,
                versioned_tags=versioned_tags,
                backend=resolved_backend,
            )
            if use_etag or vary_on:
                cache_key = representation_key(request, cache_key, vary_on)
            setattr(request, "_cache_page_key", cache_key)
            cached_response = resolved_backend.get(cache_key)
            rebuild = getattr(request, "_bust_cache", False)
            if cached_response is not None:
                rebuild = (
                    rebuild
                    or request_requires_revalidation(request)
                    or snapshot_requires_rebuild(cached_response, etag=use_etag)
                    or not response_allows_cache(
                        cached_response, vary_on, check_vary=use_etag or bool(vary_on)
                    )
                )
            if cached_response is not None and not rebuild:
                setattr(request, "_cache_page_status", "hit")
                setattr(request, "_cache_update_cache", False)
                return validate_cached_response(
                    request,
                    cached_response,
                    getattr(cached_response, "_cache_page_metadata"),
                    vary_on=vary_on,
                    max_age=max_age,
                    conditional=use_etag,
                )
            if cached_response is not None:
                # Rebuild first even when the client sent the old ETag. Deleting
                # prevents a failed or newly uncacheable rebuild reviving it.
                resolved_backend.delete(cache_key)

            setattr(request, "_cache_page_status", "miss")
            response = view_func(request, *args, **kwargs)
            setattr(request, "_cache_update_cache", False)
            if response.status_code != 200:
                return response
            if not response_allows_cache(
                response, vary_on, check_vary=use_etag or bool(vary_on)
            ):
                return forbid_cache(response)

            def store_response(rendered_response):
                resolved_timeout = (
                    timeout(rendered_response) if callable(timeout) else timeout
                )
                final_response = resolved_backend.prepare_response(
                    rendered_response, resolved_tags.keys
                )
                if not response_allows_cache(
                    final_response, vary_on, check_vary=use_etag or bool(vary_on)
                ):
                    return forbid_cache(final_response)
                try:
                    metadata = make_metadata(
                        final_response, resolved_timeout, etag=use_etag
                    )
                except (ValueError, TypeError, UnicodeDecodeError):
                    # Invalid JSON cannot receive a canonical validator.
                    return forbid_cache(final_response)
                setattr(final_response, "_cache_page_metadata", metadata)
                entry = CacheEntry(
                    key=cache_key,
                    response=final_response,
                    timeout=resolved_timeout,
                    surrogate_keys=indexed_tags.keys,
                    metadata=metadata,
                )
                resolved_backend.set(entry)
                return validate_cached_response(
                    request,
                    final_response,
                    metadata,
                    vary_on=vary_on,
                    max_age=max_age,
                    conditional=use_etag,
                )

            if (
                hasattr(response, "render")
                and callable(response.render)
                and not getattr(response, "is_rendered", False)
            ):
                response.add_post_render_callback(store_response)
            else:
                response = store_response(response)
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
) -> tuple[SurrogateKeySet, list[Versioned], SurrogateKeySet]:
    """
    Resolve tags to SurrogateKeySet and list of Versioned tags.

    Returns:
        (resolved_tags, versioned_tags, indexed_tags)
    """
    result = SurrogateKeySet()
    indexed = SurrogateKeySet()
    versioned_list: list[Versioned] = []

    if tags is None:
        return result, versioned_list, indexed

    for item in tags:
        if isinstance(item, Versioned):
            versioned_list.append(item)
            result.add(item.resolve_name(request))
        elif isinstance(item, str):
            result.add(item)
            indexed.add(item)
        elif callable(item):
            keys = item(request)
            if isinstance(keys, str):
                result.add(keys)
                indexed.add(keys)
            elif keys:
                result.add(*keys)
                indexed.add(*keys)

    return result, versioned_list, indexed


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

    return _invalidate_tag(b, tag)


def _invalidate_tag(backend: BaseCacheBackend, tag: str) -> int:
    # A tag can be used by both versioned and ordinary entries. Only ordinary
    # entries are indexed, so the common version-only path remains O(1).
    version = 0
    try:
        version = backend.increment_group_version(tag)
    except (NotImplementedError, ValueError):
        pass
    deleted = backend.invalidate_by_surrogate(tag)
    return deleted or version


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

    return sum(_invalidate_tag(b, tag) for tag in tags)
