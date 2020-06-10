import hashlib

from django.core.cache import cache


def generate_query_params_cache_key(request) -> str:
    """
    generates a cache key for a given request using query params
    """
    sorted_query_params = sorted(request.GET.keys(), key=lambda x: x.lower())
    return "-".join(f"{key}:{request.GET[key]}" for key in sorted_query_params)


def generate_cache_key(request) -> str:
    """
    generate a key using generate_cache_key and appends request path to it.
    """
    return f'{generate_query_params_cache_key(request)}-{request.path.replace("-", "")}'


def invalidate_group_caches(group: str):
    """
    This allows O(1) invalidation, but it only works with cached keys that has a ttl,
    as the old versions will expire gradually.
    we're not using pattern delete here for a performance reason.
    """
    try:
        cache.incr(group)
    except ValueError:
        pass


def hash_key(key: str) -> str:
    # http://adamnengland.com/2012/11/15/redis-performance-does-key-length-matter/
    # md5-ing the keys to save storage on cache and speed up look ups.
    return hashlib.md5(key.encode('utf-8')).hexdigest()
