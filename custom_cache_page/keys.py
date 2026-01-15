import hashlib

from django.http import HttpRequest


def generate_query_params_cache_key(request: HttpRequest) -> str:
    """
    Generates a cache key for a given request using query params.
    """
    sorted_query_params = sorted(request.GET.keys(), key=lambda x: x.lower())
    return "-".join(f"{key}:{request.GET[key]}" for key in sorted_query_params)


def generate_cache_key(request: HttpRequest) -> str:
    """
    Generate a key using generate_cache_key and appends request path to it.
    """
    return f"{generate_query_params_cache_key(request)}-{request.path.replace('-', '')}"


def hash_key(key: str) -> str:
    """
    Hash cache keys using MD5 for storage efficiency and faster lookups.

    Reference: http://adamnengland.com/2012/11/15/redis-performance-does-key-length-matter/
    """
    return hashlib.md5(key.encode("utf-8")).hexdigest()
