"""Opt-in HTTP validation for cached responses, independent of application policy."""

import hashlib
import json
import math
import time
from typing import Any, Optional

from django.http import HttpRequest, HttpResponse
from django.utils.cache import (
    get_conditional_response,
    patch_cache_control,
    patch_vary_headers,
)
from django.utils.http import http_date, parse_http_date_safe

from .keys import hash_key


def has_cache_directive(value: str, directive: str) -> bool:
    return any(
        part.split("=", 1)[0].strip().lower() == directive for part in value.split(",")
    )


def cache_policy(value: str) -> dict[str, str]:
    result = {}
    for part in value.split(","):
        name, _, argument = part.strip().partition("=")
        name = name.lower()
        # Multiple freshness values are ambiguous; never pick the most generous.
        if name in result and name in ("max-age", "s-maxage"):
            result[name] = ""
        else:
            result[name] = argument.strip().strip('"')
    return result


def request_allows_cache(request: HttpRequest) -> bool:
    # Authentication and application-specific personalization belong in only_if.
    return request.method == "GET" and not has_cache_directive(
        request.headers.get("Cache-Control", ""), "no-store"
    )


def request_requires_revalidation(request: HttpRequest) -> bool:
    policy = cache_policy(request.headers.get("Cache-Control", ""))
    return (
        "no-cache" in policy
        or policy.get("max-age") == "0"
        or has_cache_directive(request.headers.get("Pragma", ""), "no-cache")
    )


def forbid_cache(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "no-store"
    if hasattr(response, "add_post_render_callback") and not getattr(
        response, "is_rendered", True
    ):
        getattr(response, "add_post_render_callback")(forbid_cache)
    return response


def response_allows_cache(
    response: HttpResponse, vary_on: tuple[str, ...], *, check_vary: bool = True
) -> bool:
    policy = response.get("Cache-Control", "")
    supported_vary = {header.lower() for header in vary_on}
    return (
        response.status_code == 200
        and not response.streaming
        and not response.cookies
        and not response.has_header("Set-Cookie")
        and not has_cache_directive(policy, "private")
        and not has_cache_directive(policy, "no-store")
        and (
            not check_vary
            or all(
                header.strip().lower() in supported_vary
                for header in response.get("Vary", "").split(",")
                if header.strip()
            )
        )
    )


def representation_key(
    request: HttpRequest, base_key: str, vary_on: tuple[str, ...]
) -> str:
    # Read effective META, since middleware may mutate it after request.headers
    # was first materialized. Include the full URL even for lossy user key funcs.
    variants = []
    for header in vary_on:
        name = header.upper().replace("-", "_")
        meta_name = (
            name if name in ("CONTENT_TYPE", "CONTENT_LENGTH") else f"HTTP_{name}"
        )
        variants.append((header.lower(), request.META.get(meta_name, "")))
    payload = json.dumps(
        [base_key, request.get_full_path(), request.get_host(), variants],
        separators=(",", ":"),
    )
    return hash_key(f"http-v1:{payload}")


def make_etag(response: HttpResponse) -> str:
    content = response.content
    media_type = response.get("Content-Type", "").split(";", 1)[0].lower()
    if response.get("Content-Encoding", "identity").lower() == "identity" and (
        media_type == "application/json" or media_type.endswith("+json")
    ):
        content = json.dumps(
            json.loads(content),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    return f'W/"{hashlib.sha256(content).hexdigest()}"'


def make_metadata(
    response: HttpResponse, timeout: int, *, etag: bool = True
) -> dict[str, Any]:
    now = time.time()
    date = parse_http_date_safe(response.get("Date", ""))
    date = now if date is None else date
    try:
        age = max(0, int(response.get("Age", "0")))
    except ValueError:
        age = 2**63 - 1
    initial_age = max(0, now - date, age)
    policy = cache_policy(response.get("Cache-Control", ""))
    lifetimes = []
    for name in ("max-age", "s-maxage"):
        if name in policy:
            value = policy[name]
            lifetimes.append(int(value) if value.isdigit() else 0)
    if not lifetimes:
        expires = parse_http_date_safe(response.get("Expires", ""))
        if expires is not None:
            lifetimes.append(max(0, expires - date))
    lifetime = min(lifetimes) if lifetimes else timeout
    return {
        "etag": make_etag(response) if etag else None,
        "expires_at": now + timeout,
        "fresh_until": now + max(0, min(timeout, lifetime - initial_age)),
        "stored_at": now,
        "origin_date": date,
        "origin_age": age,
    }


def snapshot_requires_rebuild(response: HttpResponse, *, etag: bool = True) -> bool:
    metadata = getattr(response, "_cache_page_metadata", {})
    return (
        (etag and not metadata.get("etag"))
        or metadata.get("expires_at", 0) <= time.time()
        or metadata.get("fresh_until", 0) <= time.time()
        or has_cache_directive(response.get("Cache-Control", ""), "no-cache")
    )


def validate_cached_response(
    request: HttpRequest,
    response: HttpResponse,
    metadata: dict[str, Any],
    *,
    vary_on: tuple[str, ...],
    max_age: Optional[int],
    conditional: bool = True,
) -> HttpResponse:
    now = time.time()
    remaining = max(
        0, math.floor(min(metadata["expires_at"], metadata["fresh_until"]) - now)
    )
    if max_age is not None:
        remaining = min(remaining, max_age)
    policy = cache_policy(response.get("Cache-Control", ""))
    # Django's patch helper int() parses existing max-age. Replace freshness
    # directives ourselves first so invalid/quoted/duplicate values cannot raise
    # or accidentally override the conservative remaining lifetime above.
    response["Cache-Control"] = ", ".join(
        part.strip()
        for part in response.get("Cache-Control", "").split(",")
        if part.split("=", 1)[0].strip().lower() not in ("max-age", "s-maxage")
        and part.strip()
    )
    patch_cache_control(response, max_age=remaining, must_revalidate=True)
    if "s-maxage" in policy:
        patch_cache_control(response, s_maxage=remaining)
    # Issue freshness relative to this origin response; remaining already includes
    # the stored response's Date/Age and time spent in the origin cache.
    response["Date"] = http_date(now)
    response["Age"] = "0"
    response["Expires"] = http_date(now + remaining)
    if conditional and metadata.get("etag"):
        response["ETag"] = metadata["etag"]
    patch_vary_headers(response, vary_on)
    if conditional and metadata.get("etag"):
        validated = get_conditional_response(
            request, etag=metadata["etag"], response=response
        )
        return validated if validated is not None else response
    return response
