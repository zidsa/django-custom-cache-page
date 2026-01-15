"""
Django Custom Cache Page

A flexible cache_page decorator with surrogate-key support and pluggable backends.
"""

from .decorators import (
    Versioned,
    cache_page,
    invalidate_tag,
    invalidate_tags,
    versioned,
)
from .indexes import (
    BaseSurrogateIndex,
    DjangoCacheIndex,
    NullSurrogateIndex,
    RedisSurrogateIndex,
)
from .keys import generate_cache_key, generate_query_params_cache_key, hash_key
from .surrogates import (
    SurrogateKeySet,
    surrogate_from_model,
    surrogate_from_path,
    surrogate_from_query_params,
    surrogate_from_user,
    surrogate_from_view,
)

__version__ = "1.0.0"

__all__ = [
    # Decorator
    "cache_page",
    # Versioned tags
    "versioned",
    "Versioned",
    # Invalidation
    "invalidate_tag",
    "invalidate_tags",
    # Surrogate indexes
    "BaseSurrogateIndex",
    "DjangoCacheIndex",
    "RedisSurrogateIndex",
    "NullSurrogateIndex",
    # Key utilities
    "generate_cache_key",
    "generate_query_params_cache_key",
    "hash_key",
    # Surrogate key utilities
    "SurrogateKeySet",
    "surrogate_from_model",
    "surrogate_from_path",
    "surrogate_from_query_params",
    "surrogate_from_user",
    "surrogate_from_view",
]
