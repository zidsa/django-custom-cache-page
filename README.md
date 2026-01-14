# django-custom-cache-page

[![Python](https://img.shields.io/pypi/pyversions/django-custom-cache-page)](https://pypi.org/project/django-custom-cache-page/)
[![Django](https://img.shields.io/badge/django-4.2%20%7C%205.0%20%7C%205.1%20%7C%206.0-blue)](https://pypi.org/project/django-custom-cache-page/)
[![Coverage](https://codecov.io/gh/zidsa/django-custom-cache-page/graph/badge.svg)](https://codecov.io/gh/zidsa/django-custom-cache-page)
[![License](https://img.shields.io/github/license/zidsa/django-custom-cache-page)](https://github.com/zidsa/django-custom-cache-page/blob/master/LICENSE)

A `cache_page` decorator that gives you control over cache keys and invalidation.

## Why not Django's built-in `cache_page`?

Django's `cache_page` generates cache keys automatically from the URL, headers, and cookies. You can't easily control what gets cached or invalidate specific entries when your data changes.

This package solves that:

```python
# Django's cache_page - no control over keys, no way to invalidate
@cache_page(3600)
def product_list(request):
    ...

# This package - you control the key, you can invalidate by tag
@cache_page(timeout=3600, key_func=lambda r: r.path, tags=["products"])
def product_list(request):
    ...

# When products change, invalidate all related caches
invalidate_tag("products")
```

## Features

- **Custom cache keys** - Define exactly what makes a cache entry unique
- **Cache tags** - Group related cache entries for bulk invalidation
- **Instant invalidation** - Versioned tags invalidate millions of entries in O(1)
- **Pluggable backends** - Works with Django cache, Redis, or custom backends

## Installation

```bash
pip install django-custom-cache-page

# With Redis support (for RedisSurrogateIndex)
pip install django-custom-cache-page[redis]
```

## Quick Start

```python
from django.http import HttpResponse
from custom_cache_page import cache_page

@cache_page(
    timeout=3600,
    key_func=lambda r: r.path,
)
def my_view(request):
    return HttpResponse("Hello, World!")
```

## Usage

### Basic Caching

```python
from custom_cache_page import cache_page

@cache_page(
    timeout=3600,                    # Cache for 1 hour
    key_func=lambda r: r.path,       # Cache key from URL path
)
def product_list(request):
    ...
```

### Cache Tags (Surrogate Keys)

Tags allow you to invalidate groups of related cache entries:

```python
from custom_cache_page import cache_page, invalidate_tag

@cache_page(
    timeout=3600,
    key_func=lambda r: r.path,
    tags=[
        "products",                          # Static tag
        lambda r: f"category-{r.GET.get('cat')}",  # Dynamic tag
    ],
)
def product_list(request):
    ...

# Later, invalidate all caches tagged with "products"
invalidate_tag("products")
```

### O(1) Versioned Invalidation

For high-traffic applications, use `versioned()` tags for instant invalidation regardless of cache size:

```python
from custom_cache_page import cache_page, versioned, invalidate_tag

@cache_page(
    timeout=3600,
    key_func=lambda r: r.path,
    tags=[
        versioned("products"),  # O(1) invalidation via version increment
        "category",             # Regular tag (deletes entries)
    ],
)
def product_list(request):
    ...

# Invalidation is O(1) - just increments a version number
invalidate_tag("products")
```

**How it works:** Versioned tags embed a version number in the cache key. Invalidation simply increments the version, making all existing cache entries instantly stale without scanning or deleting them.

### Dynamic Tags

Tags can be callables that receive the request:

```python
@cache_page(
    timeout=3600,
    key_func=lambda r: r.path,
    tags=[
        lambda r: f"user-{r.user.pk}",           # Per-user tag
        lambda r: f"store-{r.headers.get('X-Store-ID')}",
        lambda r: [f"a-{r.GET.get('a')}", f"b-{r.GET.get('b')}"],  # Multiple tags
    ],
)
def dashboard(request):
    ...
```

### Conditional Caching

```python
@cache_page(
    timeout=3600,
    key_func=lambda r: r.path,
    only_if=lambda r: r.user.is_anonymous,  # Only cache for anonymous users
)
def public_page(request):
    ...
```

### Bypass Cache

Set `request.do_not_cache = True` to skip caching for specific requests:

```python
def my_view(request):
    if request.GET.get("preview"):
        request.do_not_cache = True
    ...
```

## Key Generation Utilities

Built-in key generators:

```python
from custom_cache_page import (
    generate_cache_key,              # Path + query params
    generate_query_params_cache_key, # Query params only
    hash_key,                        # MD5 hash utility
)

@cache_page(
    timeout=3600,
    key_func=generate_cache_key,
)
def my_view(request):
    ...
```

## Surrogate Key Generators

Built-in surrogate key generators for common patterns:

```python
from custom_cache_page import (
    surrogate_from_path,         # Key from URL path
    surrogate_from_model,        # Key for model instances
    surrogate_from_user,         # Key for authenticated user
    surrogate_from_query_params, # Keys from query parameters
)

@cache_page(
    timeout=3600,
    key_func=lambda r: r.path,
    tags=[
        surrogate_from_path,                      # "path-api-products"
        lambda r: surrogate_from_model("Product", r.GET.get("id")),
        surrogate_from_user,                      # "user-123" or None
    ],
)
def product_detail(request):
    ...
```

## Custom Backends

You can create custom backends by extending `BaseCacheBackend`. This is useful for CDN integration (Fastly, Cloudflare, etc.) or custom caching strategies.

### Example: Fastly CDN Backend

```python
import requests
from django.http import HttpResponse
from custom_cache_page.backends.base import BaseCacheBackend, CacheEntry


class FastlyBackend(BaseCacheBackend):
    """Backend that adds Surrogate-Key headers for Fastly CDN."""

    def __init__(self, api_token: str, service_id: str, **options):
        super().__init__(**options)
        self.api_token = api_token
        self.service_id = service_id

    def get(self, key: str):
        # Fastly handles caching at the edge
        return None

    def set(self, entry: CacheEntry):
        # Caching handled by Fastly based on Cache-Control headers
        pass

    def delete(self, key: str):
        return False

    def invalidate_by_surrogate(self, surrogate_key: str) -> int:
        """Purge by surrogate key via Fastly API."""
        response = requests.post(
            f"https://api.fastly.com/service/{self.service_id}/purge/{surrogate_key}",
            headers={
                "Fastly-Key": self.api_token,
                "Fastly-Soft-Purge": "1",
            },
        )
        response.raise_for_status()
        return 1

    def prepare_response(self, response: HttpResponse, surrogate_keys: list[str]):
        """Add Surrogate-Key header for Fastly."""
        if surrogate_keys:
            response["Surrogate-Key"] = " ".join(surrogate_keys)
        return response
```

### Example: Cloudflare CDN Backend

```python
import requests
from django.http import HttpResponse
from custom_cache_page.backends.base import BaseCacheBackend, CacheEntry


class CloudflareBackend(BaseCacheBackend):
    """Backend that adds Cache-Tag headers for Cloudflare CDN."""

    def __init__(self, api_token: str, zone_id: str, **options):
        super().__init__(**options)
        self.api_token = api_token
        self.zone_id = zone_id

    def get(self, key: str):
        return None

    def set(self, entry: CacheEntry):
        pass

    def delete(self, key: str):
        return False

    def invalidate_by_surrogate(self, surrogate_key: str) -> int:
        """Purge by cache tag via Cloudflare API."""
        response = requests.post(
            f"https://api.cloudflare.com/client/v4/zones/{self.zone_id}/purge_cache",
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
            json={"tags": [surrogate_key]},
        )
        response.raise_for_status()
        return 1

    def prepare_response(self, response: HttpResponse, surrogate_keys: list[str]):
        """Add Cache-Tag header for Cloudflare."""
        if surrogate_keys:
            response["Cache-Tag"] = " ".join(surrogate_keys)
        return response
```

### Registering Custom Backends

```python
# settings.py
CUSTOM_CACHE_PAGE = {
    "DEFAULT_BACKEND": "myapp.backends.FastlyBackend",
    "BACKENDS": {
        "fastly": {
            "BACKEND": "myapp.backends.FastlyBackend",
            "OPTIONS": {
                "api_token": "your-token",
                "service_id": "your-service-id",
            },
        },
    },
}
```

### Composite Backend

Combine multiple backends (e.g., local Django cache + CDN headers):

```python
# settings.py
CUSTOM_CACHE_PAGE = {
    "DEFAULT_BACKEND": "composite",
    "BACKENDS": {
        "django": {
            "BACKEND": "django",
            "OPTIONS": {"cache_name": "default"},
        },
        "fastly": {
            "BACKEND": "myapp.backends.FastlyBackend",
            "OPTIONS": {"api_token": "...", "service_id": "..."},
        },
        "composite": {
            "BACKEND": "composite",
            "OPTIONS": {
                "backends": ["django", "fastly"],
            },
        },
    },
}
```

## Surrogate Index

The Django backend uses a surrogate index to track which cache keys belong to which tags. This enables bulk invalidation.

### Auto-detection (Default)

When using django-redis, the `DjangoCacheIndex` automatically detects the Redis client and uses native Redis SADD:

```python
# settings.py - No extra configuration needed
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://localhost:6379/1",
    }
}

# The DjangoCacheBackend will auto-detect Redis and use SADD
```

### Explicit Redis Index

For more control, use `RedisSurrogateIndex` directly:

```python
from custom_cache_page import RedisSurrogateIndex
from custom_cache_page.backends.django import DjangoCacheBackend

backend = DjangoCacheBackend(
    cache_name="default",
    surrogate_index=RedisSurrogateIndex(
        url="redis://localhost:6379/0",
        timeout=86400,  # Index TTL (default: 24h)
        prefix="_surrogate:",  # Key prefix
    ),
)
```

Or with an existing Redis client:

```python
import redis
from custom_cache_page import RedisSurrogateIndex

redis_client = redis.from_url("redis://localhost:6379/0")
index = RedisSurrogateIndex(redis_client=redis_client)
```

### Null Index (CDN-only)

When using CDN backends where invalidation happens via API, disable local index tracking:

```python
from custom_cache_page import NullSurrogateIndex
from custom_cache_page.backends.django import DjangoCacheBackend

backend = DjangoCacheBackend(
    cache_name="default",
    surrogate_index=NullSurrogateIndex(),
)
```

### Available Index Classes

| Class | Use Case |
|-------|----------|
| `DjangoCacheIndex` | Default. Auto-detects Redis, falls back to standard cache |
| `RedisSurrogateIndex` | Explicit Redis with native SADD |
| `NullSurrogateIndex` | No-op for CDN-only setups |
| `BaseSurrogateIndex` | Abstract base for custom implementations |

## API Reference

### `cache_page`

```python
@cache_page(
    timeout: int,                    # Cache TTL in seconds
    key_func: Callable[[HttpRequest], str],  # Cache key generator
    *,
    tags: list[str | Callable | Versioned] = None,  # Cache tags
    prefix: str = None,              # Key prefix
    backend: str | BaseCacheBackend = None,  # Backend name or instance
    cache_name: str = "default",     # Django cache alias
    only_if: Callable[[HttpRequest], bool] = None,  # Condition function
)
```

### `versioned`

```python
versioned(name: str, timeout: int = 864000) -> Versioned
```

Wrap a tag name for O(1) versioned invalidation. The `timeout` parameter sets the TTL for the version key (default: 10 days).

### `invalidate_tag`

```python
invalidate_tag(tag: str, backend: str = None) -> int
```

Invalidate all caches with the given tag. Returns the number of invalidated entries (or new version number for versioned tags).

### `invalidate_tags`

```python
invalidate_tags(tags: list[str], backend: str = None) -> int
```

Batch invalidation of multiple tags.

## Upgrading from v0.x

Version 1.0 introduces breaking changes. See [HISTORY.md](HISTORY.md) for the full changelog.

**Key changes:**

```python
# Old (v0.x)
from custom_cache_page.cache import cache_page
from custom_cache_page.utils import invalidate_group_caches

@cache_page(
    timeout=3600,
    key_func=lambda r: r.path,
    versioned=True,
    group_func=lambda r: "my-group",
)

invalidate_group_caches("my-group")

# New (v1.0)
from custom_cache_page import cache_page, versioned, invalidate_tag

@cache_page(
    timeout=3600,
    key_func=lambda r: r.path,
    tags=[versioned("my-group")],
)

invalidate_tag("my-group")
```

## Development

```bash
git clone https://github.com/zidsa/django-custom-cache-page.git
cd django-custom-cache-page
pip install -e ".[dev]"

# Run tests
pytest

# Run tests across Python/Django versions
tox

# Lint and format
ruff check .
ruff format .

# Type check
pyright custom_cache_page/
```

## License

MIT License - see [LICENSE](LICENSE) for details.
