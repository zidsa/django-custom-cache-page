# Changelog

## 1.0.0 (2026-01-14)

### Breaking Changes

- **Import paths changed**:
  - Old: `from custom_cache_page.cache import cache_page`
  - New: `from custom_cache_page import cache_page`
- **Removed modules**: `cache.py` and `utils.py` are removed. Import from package root instead.
- **API changed**: `versioned`, `group_func` replaced with unified `tags` parameter
- **Minimum Python version**: 3.9+ (was 3.6+)
- **Minimum Django version**: 4.2+ (was 2.0+)

### New Features

- **Unified `tags` parameter**: Replaces old `versioned`/`group_func` with a single, flexible API:
  ```python
  @cache_page(
      timeout=3600,
      key_func=lambda r: r.path,
      tags=[
          versioned("products"),           # O(1) invalidation via version increment
          "category",                      # Regular surrogate key
          lambda r: f"user-{r.user.pk}",   # Dynamic tag from request
      ],
  )
  ```

- **`versioned()` wrapper**: O(1) cache invalidation via version incrementing
  ```python
  from custom_cache_page import versioned, invalidate_tag

  tags=[versioned("products")]  # Uses version number in cache key

  invalidate_tag("products")    # Just increments version (O(1))
  ```

- **Pluggable backends**: Abstract backend interface for custom implementations:
  - `DjangoCacheBackend` - Uses Django's cache framework (default)
  - `CompositeBackend` - Combine multiple backends
  - Easy to extend for CDN integration (Fastly, Cloudflare, etc.)

- **New invalidation functions**:
  - `invalidate_tag(tag)` - Invalidate by tag (O(1) for versioned, deletes for regular)
  - `invalidate_tags(tags)` - Batch invalidation

- **Surrogate key generators**:
  - `surrogate_from_path(request)` - Key from URL path
  - `surrogate_from_model(name, pk)` - Key for model instances
  - `surrogate_from_user(request)` - Key for authenticated user
  - `surrogate_from_query_params(request)` - Keys from query params

- **Configuration via Django settings**:
  ```python
  CUSTOM_CACHE_PAGE = {
      "DEFAULT_BACKEND": "django",
      "BACKENDS": {
          "fastly": {
              "BACKEND": "fastly",
              "OPTIONS": {"api_token": "...", "service_id": "..."},
          },
      },
  }
  ```

### Installation

```bash
pip install django-custom-cache-page
```

## 0.4 (2026-01-14)

- Added support for Python 3.9-3.13
- Added support for Django 4.2-6.0
- Dropped support for Python 3.6-3.8
- Dropped support for Django 2.0-4.1

## 0.3

- Initial public release
