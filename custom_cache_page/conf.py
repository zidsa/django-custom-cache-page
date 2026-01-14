from typing import Any

from django.conf import settings
from django.utils.module_loading import import_string

from .backends.base import BaseCacheBackend

BUILTIN_BACKENDS = {
    "django": "custom_cache_page.backends.django.DjangoCacheBackend",
    "composite": "custom_cache_page.backends.composite.CompositeBackend",
}

_backend_cache: dict[str, BaseCacheBackend] = {}


def get_settings() -> dict[str, Any]:
    """
    Get custom cache page settings from Django settings.

    Example settings.py:

        CUSTOM_CACHE_PAGE = {
            "DEFAULT_BACKEND": "django",
            "BACKENDS": {
                "django": {
                    "BACKEND": "django",
                    "OPTIONS": {"cache_name": "default"},
                },
                "my_cdn": {
                    "BACKEND": "myapp.backends.MyCDNBackend",
                    "OPTIONS": {"api_key": "..."},
                },
            },
        }
    """
    return getattr(settings, "CUSTOM_CACHE_PAGE", {})


def get_backend_class(backend_path: str) -> type:
    """Import and return backend class from dotted path."""
    if backend_path in BUILTIN_BACKENDS:
        backend_path = BUILTIN_BACKENDS[backend_path]

    return import_string(backend_path)


def get_backend_by_name(name: str) -> BaseCacheBackend:
    """
    Get a backend instance by name from settings.

    Backends are cached for reuse.
    """
    if name in _backend_cache:
        return _backend_cache[name]

    config = get_settings()
    backends_config = config.get("BACKENDS", {})

    if name not in backends_config:
        raise ValueError(f"Unknown cache backend: {name}")

    backend_config = backends_config[name]
    backend_class = get_backend_class(backend_config.get("BACKEND", "django"))
    options = backend_config.get("OPTIONS", {})

    # Handle composite backend - resolve backend names to instances
    if (
        "backends" in options
        and options["backends"]
        and isinstance(options["backends"][0], str)
    ):
        options = options.copy()
        options["backends"] = [get_backend_by_name(b) for b in options["backends"]]

    backend = backend_class(**options)
    _backend_cache[name] = backend

    return backend


def get_default_backend(cache_name: str = "default") -> BaseCacheBackend:
    """Get the default backend."""
    config = get_settings()
    default_name = config.get("DEFAULT_BACKEND")

    if default_name:
        return get_backend_by_name(default_name)

    # Fall back to Django cache backend
    from .backends.django import DjangoCacheBackend

    return DjangoCacheBackend(cache_name=cache_name)


def clear_backend_cache() -> None:
    """Clear the backend instance cache. Useful for testing."""
    _backend_cache.clear()
