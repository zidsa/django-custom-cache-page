from typing import Callable, Optional, Union

from django.http import HttpRequest

SurrogateKeyFunc = Callable[[HttpRequest], Union[str, list[str], None]]


class SurrogateKeySet:
    """
    Represents a set of surrogate keys for a cached response.

    Surrogate keys are tags that allow bulk invalidation of related cache entries.
    """

    def __init__(self, keys: Optional[list[str]] = None) -> None:
        self._keys: list[str] = []
        if keys:
            self.add(*keys)

    def add(self, *keys: str) -> "SurrogateKeySet":
        """Add one or more surrogate keys."""
        for key in keys:
            normalized = self._normalize_key(key)
            if normalized and normalized not in self._keys:
                self._keys.append(normalized)
        return self

    def _normalize_key(self, key: str) -> Optional[str]:
        """
        Normalize a surrogate key.

        - Strips whitespace
        - Replaces spaces with hyphens (spaces are delimiters in header)
        - Returns None for empty keys
        """
        if not key:
            return None
        normalized = key.strip().replace(" ", "-")
        return normalized if normalized else None

    @property
    def keys(self) -> list[str]:
        """Return list of surrogate keys."""
        return self._keys.copy()

    def __iter__(self):
        return iter(self._keys)

    def __len__(self):
        return len(self._keys)

    def __bool__(self):
        return bool(self._keys)

    def to_header(self) -> str:
        """Format keys as space-separated header value."""
        return " ".join(self._keys)

    @classmethod
    def from_header(cls, header_value: str) -> "SurrogateKeySet":
        """Parse surrogate keys from header value."""
        if not header_value:
            return cls()
        return cls(header_value.split())


def surrogate_from_path(request: HttpRequest) -> str:
    """
    Generate surrogate key from request path.

    Example: /api/products/123/ -> "path-api-products-123"
    """
    path = request.path.strip("/").replace("/", "-") or "root"
    return f"path-{path}"


def surrogate_from_view(view_name: str) -> str:
    """
    Create a surrogate key for a specific view name.

    Usage: surrogate_keys=[surrogate_from_view("product_detail")]
    """
    return f"view-{view_name}"


def surrogate_from_model(
    model_name: str,
    pk: Optional[Union[str, int]] = None,
) -> str:
    """
    Create surrogate key for a model, optionally with specific PK.

    Usage:
        surrogate_from_model("Product")           -> "model-product"
        surrogate_from_model("Product", 123)      -> "model-product-123"
    """
    key = f"model-{model_name.lower()}"
    if pk is not None:
        key = f"{key}-{pk}"
    return key


def surrogate_from_user(request: HttpRequest) -> Optional[str]:
    """
    Generate surrogate key from authenticated user.

    Returns None for anonymous users.
    """
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return f"user-{user.pk}"
    return None


def surrogate_from_query_params(
    request: HttpRequest,
    params: Optional[list[str]] = None,
) -> list[str]:
    """
    Generate surrogate keys from query parameters.

    Args:
        request: The HTTP request
        params: Specific params to include (None = all params)

    Example: ?category=shoes&brand=nike -> ["param-category-shoes", "param-brand-nike"]
    """
    keys = []
    target_params = params if params is not None else list(request.GET.keys())

    for param in target_params:
        value = request.GET.get(param)
        if value:
            keys.append(f"param-{param}-{value}")

    return keys
