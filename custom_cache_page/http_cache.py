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

FRESHNESS_DIRECTIVES = ("max-age", "s-maxage")
SHARED_CACHE_DIRECTIVES = {"public", "must-revalidate", "s-maxage"}


def has_cache_directive(value: str, directive: str) -> bool:
    return any(
        part.split("=", 1)[0].strip().lower() == directive for part in value.split(",")
    )


def cache_policy(value: str) -> dict[str, str]:
    result = {}
    for part in value.split(","):
        name, _, argument = part.strip().partition("=")
        name = name.lower()
        if name in result and name in FRESHNESS_DIRECTIVES:
            result[name] = ""
        else:
            result[name] = argument.strip().strip('"')
    return result


def request_allows_cache(request: HttpRequest) -> bool:
    return request.method in ("GET", "HEAD") and not has_cache_directive(
        request.META.get("HTTP_CACHE_CONTROL", ""), "no-store"
    )


def request_requires_revalidation(request: HttpRequest) -> bool:
    policy = cache_policy(request.META.get("HTTP_CACHE_CONTROL", ""))
    return (
        "no-cache" in policy
        or policy.get("max-age") == "0"
        or has_cache_directive(request.META.get("HTTP_PRAGMA", ""), "no-cache")
    )


def forbid_cache(response: HttpResponse) -> HttpResponse:
    if not response.has_header("Cache-Control"):
        response["Cache-Control"] = "no-store"
    return response


def response_allows_cache(
    response: HttpResponse,
    vary_on: tuple[str, ...],
    *,
    check_vary: bool,
    authorized: bool = False,
) -> bool:
    policy = cache_policy(response.get("Cache-Control", ""))
    if (
        response.status_code != 200
        or response.streaming
        or response.cookies
        or response.has_header("Set-Cookie")
        or "private" in policy
        or "no-store" in policy
        or (authorized and not policy.keys() & SHARED_CACHE_DIRECTIVES)
    ):
        return False
    if not check_vary:
        return True
    supported_vary = {header.lower() for header in vary_on}
    return all(
        header.strip().lower() in supported_vary
        for header in response.get("Vary", "").split(",")
        if header.strip()
    )


def representation_key(
    request: HttpRequest, base_key: str, vary_on: tuple[str, ...]
) -> str:
    variants = []
    for header in vary_on:
        name = header.upper().replace("-", "_")
        if name not in ("CONTENT_TYPE", "CONTENT_LENGTH"):
            name = f"HTTP_{name}"
        variants.append((header.lower(), request.META.get(name, "")))
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
    if date is None:
        date = now
    try:
        age = max(0, int(response.get("Age", "0")))
    except ValueError:
        age = math.inf
    initial_age = max(0, now - date, age)
    policy = cache_policy(response.get("Cache-Control", ""))
    lifetimes: list[float] = [
        int(policy[name]) if policy[name].isdigit() else 0
        for name in FRESHNESS_DIRECTIVES
        if name in policy
    ]
    if not lifetimes:
        expires = parse_http_date_safe(response.get("Expires", ""))
        if expires is not None:
            lifetimes.append(max(0, expires - date))
    lifetime = min(lifetimes) if lifetimes else timeout
    return {
        "etag": (response.get("ETag") or make_etag(response)) if etag else None,
        "fresh_until": now + max(0, min(timeout, lifetime - initial_age)),
    }


def snapshot_requires_rebuild(
    response: HttpResponse, metadata: dict[str, Any], *, etag: bool = True
) -> bool:
    return (
        (etag and not metadata.get("etag"))
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
    remaining = max(0, round(metadata["fresh_until"] - now))
    if max_age is not None:
        remaining = min(remaining, max_age)
    policy = cache_policy(response.get("Cache-Control", ""))
    # patch_cache_control() int()-parses an existing max-age, so strip it first.
    response["Cache-Control"] = ", ".join(
        part.strip()
        for part in response.get("Cache-Control", "").split(",")
        if part.strip()
        and part.split("=", 1)[0].strip().lower() not in FRESHNESS_DIRECTIVES
    )
    directives = {"max_age": remaining}
    if "s-maxage" in policy:
        directives["s_maxage"] = remaining
    patch_cache_control(response, **directives)
    response["Date"] = http_date(now)
    response["Expires"] = http_date(now + remaining)
    if "Age" in response:
        del response["Age"]
    if vary_on:
        patch_vary_headers(response, vary_on)
    etag = metadata.get("etag") if conditional else None
    if not etag:
        return response
    response["ETag"] = etag
    validated = get_conditional_response(
        request,
        etag=etag,
        last_modified=parse_http_date_safe(response.get("Last-Modified", "")),
        response=response,
    )
    return validated or response
