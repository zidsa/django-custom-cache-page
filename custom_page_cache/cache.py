from django.utils.cache import patch_response_headers
from functools import wraps

from .utils import hash_key
from django.core.cache import cache


def _cache_page(
        timeout,
        key_func,
        prefix=None,
        group_func=None,
        versioned=False,
        versions_timeout=864000
):
    def _cache(view_func):
        @wraps(view_func)
        def __cache(request, *args, **kwargs):
            if getattr(request, 'do_not_cache', False):
                return view_func(request, *args, **kwargs)
            group = group_func(request) if group_func else None
            group_version = cache.get_or_set(group, 1, timeout=versions_timeout) if versioned else 0
            cache_key = hash_key(f'{prefix}:{group}:{group_version}:{key_func(request)}')
            response = cache.get(cache_key)
            process_caching = not response or getattr(request, '_bust_cache', False)
            if process_caching:
                response = view_func(request, *args, **kwargs)
                if response.status_code == 200:
                    patch_response_headers(response, timeout)
                    if hasattr(response, 'render') and callable(response.render):
                        def set_cache(val) -> None:
                            cache.set(cache_key, val, timeout)
                        response.add_post_render_callback(set_cache)
                    else:
                        cache.set(cache_key, response, timeout)
            setattr(request, '_cache_update_cache', False)
            return response
        return __cache
    return _cache


def cache_page(
    timeout,
    key_func,
    versioned=False,
    group_func=None,
    prefix=None
):
    return _cache_page(
        timeout,
        key_func,
        prefix=prefix,
        group_func=group_func,
        versioned=versioned
    )
