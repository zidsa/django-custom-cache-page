import gzip
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.template.response import SimpleTemplateResponse
from django.utils.http import http_date

from custom_cache_page import (
    cache_page,
    http_cache,
    invalidate_tag,
    invalidate_tags,
    versioned,
)
from custom_cache_page.backends.django import DjangoCacheBackend


@pytest.fixture(autouse=True)
def allowed_hosts(settings):
    settings.ALLOWED_HOSTS = ["testserver", "other.example"]


@pytest.fixture
def clock(monkeypatch):
    now = [1700000000.0]
    monkeypatch.setattr(http_cache.time, "time", lambda: now[0])
    return now


def make_view(*, response=None, **options):
    state = {"calls": 0, "value": {"name": "Product", "price": 10}}

    @cache_page(
        timeout=3600, key_func=options.pop("key_func", lambda r: r.path), **options
    )
    def view(request):
        state["calls"] += 1
        return response(request, state) if response else JsonResponse(state["value"])

    return view, state


def test_matching_validator_skips_view_and_returns_bodyless_304(request_factory, clock):
    view, state = make_view(etag=True, max_age=300)
    first = view(request_factory.get("/products/1"))
    assert first["ETag"].startswith('W/"')
    assert first["Cache-Control"] == "max-age=300"
    clock[0] += 90
    second = view(request_factory.get("/products/1", HTTP_IF_NONE_MATCH=first["ETag"]))
    assert second.status_code == 304
    assert second.content == b""
    assert second["ETag"] == first["ETag"]
    assert state["calls"] == 1


def test_canonical_json_object_order_but_not_array_order(request_factory, clock):
    view, state = make_view(etag=True)
    first = view(request_factory.get("/products"))
    state["value"] = {"price": 10, "name": "Product"}
    request = request_factory.get("/products", HTTP_IF_NONE_MATCH=first["ETag"])
    request._bust_cache = True
    assert view(request).status_code == 304
    state["value"] = {"list": [1, 2]}
    first_array = view(request_factory.get("/arrays"))
    state["value"] = {"list": [2, 1]}
    request = request_factory.get("/arrays", HTTP_IF_NONE_MATCH=first_array["ETag"])
    request._bust_cache = True
    assert view(request).status_code == 200


@pytest.mark.parametrize(
    "trigger", ["timeout", "bust", "no-cache", "max-age=0", "pragma", "generation"]
)
@pytest.mark.parametrize("changed", [False, True])
def test_rebuilds_before_comparing_old_validator(
    request_factory, clock, trigger, changed
):
    view, state = make_view(etag=True, tags=[versioned("products")])
    first = view(request_factory.get("/products"))
    if changed:
        state["value"]["price"] = 20
    kwargs = {"HTTP_IF_NONE_MATCH": first["ETag"]}
    if trigger == "timeout":
        clock[0] += 3601
    elif trigger in ("no-cache", "max-age=0"):
        kwargs["HTTP_CACHE_CONTROL"] = trigger
    elif trigger == "pragma":
        kwargs["HTTP_PRAGMA"] = "no-cache"
    elif trigger == "generation":
        invalidate_tag("products")
    request = request_factory.get("/products", **kwargs)
    if trigger == "bust":
        request._bust_cache = True
    result = view(request)
    assert state["calls"] == 2
    assert result.status_code == (200 if changed else 304)


def test_expired_metadata_cannot_validate_even_if_cache_entry_survives(
    request_factory, clock
):
    view, state = make_view(etag=True)
    request = request_factory.get("/products")
    first = view(request)
    cached = cache.get(request._cache_page_key)
    cached["metadata"]["fresh_until"] = clock[0] - 1
    cache.set(request._cache_page_key, cached, 3600)
    second = view(request_factory.get("/products", HTTP_IF_NONE_MATCH=first["ETag"]))
    assert second.status_code == 304
    assert state["calls"] == 2


@pytest.mark.parametrize("status", [404, 500])
def test_rebuild_error_does_not_validate_or_revive_old_snapshot(
    request_factory, clock, status
):
    view, state = make_view(
        etag=True,
        response=lambda r, s: JsonResponse(s["value"], status=s.get("status", 200)),
    )
    first = view(request_factory.get("/products"))
    state["status"] = status
    request = request_factory.get("/products", HTTP_IF_NONE_MATCH=first["ETag"])
    request._bust_cache = True
    assert view(request).status_code == status
    assert view(request_factory.get("/products")).status_code == status
    assert state["calls"] == 3


@pytest.mark.parametrize("etag", [False, True])
@pytest.mark.parametrize("policy", ["private", "no-store", "PRIVATE, max-age=60"])
def test_private_and_no_store_responses_never_enter_cache(
    request_factory, etag, policy
):
    def response(request, state):
        return JsonResponse(state["value"], headers={"Cache-Control": policy})

    view, state = make_view(etag=etag, response=response)
    assert view(request_factory.get("/products"))["Cache-Control"] == policy
    view(request_factory.get("/products"))
    assert state["calls"] == 2


@pytest.mark.parametrize("etag", [False, True])
@pytest.mark.parametrize("kind", ["cookie", "header", "streaming"])
def test_cookie_and_streaming_responses_are_not_cached(request_factory, etag, kind):
    def response(request, state):
        if kind == "streaming":
            return StreamingHttpResponse([b"product"])
        result = JsonResponse(state["value"])
        if kind == "cookie":
            result.set_cookie("session", "sample")
        else:
            result["Set-Cookie"] = "session=sample"
        return result

    view, state = make_view(etag=etag, response=response)
    view(request_factory.get("/products"))
    view(request_factory.get("/products"))
    assert state["calls"] == 2


@pytest.mark.parametrize("header", ["*", "X-Unknown"])
def test_unknown_vary_refuses_cache_when_representations_are_keyed(
    request_factory, header
):
    view, state = make_view(
        etag=True,
        response=lambda r, s: JsonResponse(s["value"], headers={"Vary": header}),
    )
    assert "Cache-Control" not in view(request_factory.get("/products"))
    view(request_factory.get("/products"))
    assert state["calls"] == 2


def test_legacy_mode_ignores_response_vary(request_factory):
    view, state = make_view(
        response=lambda r, s: JsonResponse(s["value"], headers={"Vary": "Accept"}),
    )
    view(request_factory.get("/products"))
    assert view(request_factory.get("/products"))["Vary"] == "Accept"
    assert state["calls"] == 1


@pytest.mark.parametrize("etag", [False, True])
def test_request_no_store_and_only_if_bypass(request_factory, etag):
    view, state = make_view(
        etag=etag, only_if=lambda r: not r.headers.get("X-Bypass-Cache")
    )
    public = view(request_factory.get("/products"))
    assert public.status_code == 200
    no_store = view(request_factory.get("/products", HTTP_CACHE_CONTROL="no-store"))
    assert "Cache-Control" not in no_store
    bypassed = view(request_factory.get("/products", HTTP_X_BYPASS_CACHE="1"))
    assert bypassed["Cache-Control"] == "no-store"
    assert state["calls"] == 3
    view(request_factory.get("/products"))
    assert state["calls"] == 3


def test_post_bypasses_get_snapshot(request_factory):
    view, state = make_view(etag=True)
    first = view(request_factory.get("/products"))
    result = view(request_factory.post("/products", HTTP_IF_NONE_MATCH=first["ETag"]))
    assert result.status_code == 200
    assert "Cache-Control" not in result
    assert state["calls"] == 2


def test_head_reads_get_snapshot_but_never_stores(request_factory):
    view, state = make_view(etag=True)
    miss = view(request_factory.head("/products"))
    assert "ETag" not in miss
    assert view(request_factory.head("/products")).status_code == 200
    assert state["calls"] == 2
    first = view(request_factory.get("/products"))
    head = view(request_factory.head("/products"))
    assert head["ETag"] == first["ETag"]
    assert head["Cache-Control"] == first["Cache-Control"]
    conditional = view(
        request_factory.head("/products", HTTP_IF_NONE_MATCH=first["ETag"])
    )
    assert conditional.status_code == 304
    assert state["calls"] == 3


def test_last_modified_supports_if_modified_since(request_factory, clock):
    modified = http_date(clock[0] - 100)
    view, state = make_view(
        etag=True,
        response=lambda r, s: JsonResponse(
            s["value"], headers={"Last-Modified": modified}
        ),
    )
    first = view(request_factory.get("/products"))
    assert first["Last-Modified"] == modified
    assert (
        view(
            request_factory.get("/products", HTTP_IF_MODIFIED_SINCE=modified)
        ).status_code
        == 304
    )
    assert (
        view(
            request_factory.get(
                "/products", HTTP_IF_MODIFIED_SINCE=http_date(clock[0] - 200)
            )
        ).status_code
        == 200
    )
    assert state["calls"] == 1


def test_variants_use_effective_headers_and_preserve_url_dimensions(request_factory):
    view, state = make_view(
        etag=True,
        vary_on=("Accept-Language", "X-Theme", "Content-Type"),
        key_func=lambda r: "same-key",
    )
    requests = [
        request_factory.get("/products?a=1&a=2", HTTP_ACCEPT_LANGUAGE="en"),
        request_factory.get("/products?a=1&a=2", HTTP_ACCEPT_LANGUAGE="fr"),
        request_factory.get("/products?a=2&a=1", HTTP_ACCEPT_LANGUAGE="en"),
        request_factory.get(
            "/products?a=1&a=2", HTTP_ACCEPT_LANGUAGE="en", HTTP_HOST="other.example"
        ),
        request_factory.get(
            "/products?a=1&a=2",
            HTTP_ACCEPT_LANGUAGE="en",
            CONTENT_TYPE="application/json",
        ),
        request_factory.get("/products?a=1&a=2", HTTP_ACCEPT_LANGUAGE="en"),
    ]
    _ = requests[-1].headers
    requests[-1].META["HTTP_X_THEME"] = "dark"
    for request in requests:
        view(request)
        view(request)
    assert state["calls"] == len(requests)


@pytest.mark.parametrize("etag", [False, True])
def test_cached_max_age_counts_down_from_snapshot(request_factory, clock, etag):
    view, state = make_view(
        etag=etag,
        response=lambda r, s: JsonResponse(
            s["value"], headers={"Cache-Control": "max-age=30, s-maxage=20"}
        ),
    )
    first = view(request_factory.get("/products"))
    assert "max-age=20" in first["Cache-Control"]
    clock[0] += 10
    second = view(request_factory.get("/products"))
    assert http_cache.cache_policy(second["Cache-Control"]) == {
        "max-age": "10",
        "s-maxage": "10",
    }
    assert second["Date"] == http_date(clock[0])
    assert "Age" not in second
    assert "Vary" not in second
    clock[0] += 11
    view(request_factory.get("/products"))
    assert state["calls"] == 2


def test_date_age_and_expires_are_accounted_for(request_factory, clock):
    def response(request, state):
        return JsonResponse(
            state["value"],
            headers={
                "Date": http_date(clock[0] - 20),
                "Age": "40",
                "Cache-Control": "max-age=100",
            },
        )

    view, _ = make_view(etag=True, response=response)
    first = view(request_factory.get("/products"))
    assert "max-age=60" in first["Cache-Control"]
    clock[0] += 10
    assert "max-age=50" in view(request_factory.get("/products"))["Cache-Control"]
    expires_view, _ = make_view(
        etag=True,
        response=lambda r, s: JsonResponse(
            s["value"], headers={"Expires": http_date(clock[0] + 30)}
        ),
    )
    assert (
        "max-age=30" in expires_view(request_factory.get("/expires"))["Cache-Control"]
    )


def test_no_cache_response_rebuilds_each_request(request_factory, clock):
    view, state = make_view(
        etag=True,
        response=lambda r, s: JsonResponse(
            s["value"], headers={"Cache-Control": "no-cache"}
        ),
    )
    first = view(request_factory.get("/products"))
    assert (
        view(
            request_factory.get("/products", HTTP_IF_NONE_MATCH=first["ETag"])
        ).status_code
        == 304
    )
    assert state["calls"] == 2


def test_runtime_flag_off_does_not_validate_existing_tagged_entry(request_factory):
    enabled = [True]
    view, state = make_view(etag=lambda r: enabled[0], vary_on=("Accept-Language",))
    first = view(request_factory.get("/products"))
    enabled[0] = False
    assert (
        view(
            request_factory.get("/products", HTTP_IF_NONE_MATCH=first["ETag"])
        ).status_code
        == 200
    )
    assert state["calls"] == 1


def test_enabling_flag_rebuilds_entry_without_validator(request_factory):
    enabled = [False]
    view, state = make_view(etag=lambda r: enabled[0], vary_on=("Accept-Language",))
    first = view(request_factory.get("/products"))
    assert "ETag" not in first
    enabled[0] = True
    assert "ETag" in view(request_factory.get("/products"))
    assert state["calls"] == 2


class JsonTemplateResponse(SimpleTemplateResponse):
    @property
    def rendered_content(self):
        return '{"name":"Product","price":10}'


@pytest.mark.parametrize("already_rendered", [False, True])
def test_template_response_supports_conditional_post_render_result(
    request_factory, already_rendered
):
    def response(request, state):
        result = JsonTemplateResponse(None, content_type="application/json")
        return result.render() if already_rendered else result

    view, state = make_view(etag=True, response=response)
    first = view(request_factory.get("/products"))
    if not already_rendered:
        first = first.render()
    request = request_factory.get("/products", HTTP_IF_NONE_MATCH=first["ETag"])
    request._bust_cache = True
    second = view(request)
    if not already_rendered:
        second = second.render()
    assert second.status_code == 304
    assert second.content == b""


def test_post_render_cookie_policy_refuses_admission(request_factory):
    def response(request, state):
        result = JsonTemplateResponse(None, content_type="application/json")
        result.add_post_render_callback(
            lambda value: value.set_cookie("session", "sample")
        )
        return result

    view, state = make_view(etag=True, response=response)
    assert "Cache-Control" not in view(request_factory.get("/products")).render()
    view(request_factory.get("/products")).render()
    assert state["calls"] == 2


def test_invalid_json_returns_body_without_caching_or_validator(request_factory):
    view, state = make_view(
        etag=True,
        response=lambda r, s: HttpResponse(b"broken", content_type="application/json"),
    )
    response = view(request_factory.get("/products"))
    assert "Cache-Control" not in response
    assert "ETag" not in response
    view(request_factory.get("/products"))
    assert state["calls"] == 2


def test_binary_payload_round_trips_with_weak_validator(request_factory):
    content = gzip.compress(b"\xff\x00product")
    view, state = make_view(
        etag=True,
        response=lambda r, s: HttpResponse(
            content, content_type="application/octet-stream"
        ),
    )
    first = view(request_factory.get("/binary"))
    cached = view(request_factory.get("/binary"))
    assert cached.content == content
    assert cached["ETag"] == first["ETag"]
    assert (
        view(
            request_factory.get("/binary", HTTP_IF_NONE_MATCH=first["ETag"])
        ).status_code
        == 304
    )
    assert state["calls"] == 1


def test_normal_and_weak_list_and_wildcard_validator_semantics(request_factory):
    view, _ = make_view(etag=True)
    first = view(request_factory.get("/products"))
    for value in (first["ETag"][2:], f'"unrelated", {first["ETag"]}', "*"):
        assert (
            view(request_factory.get("/products", HTTP_IF_NONE_MATCH=value)).status_code
            == 304
        )
    assert (
        view(
            request_factory.get("/products", HTTP_IF_NONE_MATCH='"different"')
        ).status_code
        == 200
    )


def test_ordinary_and_versioned_tags_both_invalidate_real_cached_responses(
    request_factory,
):
    ordinary, ordinary_state = make_view(tags=["mixed"])
    versioned_view, versioned_state = make_view(tags=[versioned("mixed")])
    ordinary(request_factory.get("/ordinary"))
    versioned_view(request_factory.get("/versioned"))
    invalidate_tag("mixed")
    ordinary(request_factory.get("/ordinary"))
    versioned_view(request_factory.get("/versioned"))
    assert ordinary_state["calls"] == versioned_state["calls"] == 2


def test_regular_tag_purge_without_version_key_and_batched_invalidation(
    request_factory,
):
    first, first_state = make_view(tags=["first"])
    second, second_state = make_view(tags=["second"])
    first(request_factory.get("/first"))
    second(request_factory.get("/second"))
    invalidate_tags(["first", "second"])
    first(request_factory.get("/first"))
    second(request_factory.get("/second"))
    assert first_state["calls"] == second_state["calls"] == 2
    assert cache.get("first") is None


def test_versioned_only_tags_do_not_track_each_response_in_surrogate_index(
    request_factory,
):
    backend = DjangoCacheBackend()
    backend._surrogate_index = Mock()
    view, _ = make_view(tags=[versioned("products")], backend=backend)
    view(request_factory.get("/products"))
    backend._surrogate_index.add.assert_not_called()


def test_generation_eviction_does_not_resurrect_old_response(
    request_factory, monkeypatch
):
    epochs = iter([1000, 2000])
    monkeypatch.setattr(
        "custom_cache_page.backends.django.secrets.randbits", lambda bits: next(epochs)
    )
    view, state = make_view(tags=[versioned("products")])
    assert view(request_factory.get("/products")).content
    state["value"]["price"] = 99
    cache.delete("products")
    second = view(request_factory.get("/products"))
    assert b"99" in second.content
    assert state["calls"] == 2
    assert cache.get("products") == 2001


def test_existing_integer_generations_and_direct_increment_stay_compatible(
    request_factory,
):
    cache.set("products", 12, 3600)
    view, state = make_view(tags=[versioned("products")])
    view(request_factory.get("/products"))
    cache.incr("products")
    view(request_factory.get("/products"))
    assert state["calls"] == 2
    assert cache.get("products") == 13


def test_generation_timeout_is_shorter_than_response_timeout(request_factory, clock):
    view, state = make_view(tags=[versioned("products", timeout=10)])
    view(request_factory.get("/products"))
    first_generation = cache.get("products")
    clock[0] += 11
    view(request_factory.get("/products"))
    assert state["calls"] == 2
    assert cache.get("products") != first_generation


@pytest.mark.parametrize(
    "policy",
    [
        "max-age=5, max-age=300",
        "max-age=300, max-age=5",
        "max-age=300, s-maxage=5, s-maxage=300",
        "max-age=invalid",
    ],
)
def test_ambiguous_or_invalid_freshness_is_never_fresh(request_factory, clock, policy):
    view, state = make_view(
        etag=True,
        response=lambda r, s: JsonResponse(
            s["value"], headers={"Cache-Control": policy}
        ),
    )
    first = view(request_factory.get("/products"))
    assert "max-age=0" in first["Cache-Control"]
    view(request_factory.get("/products"))
    assert state["calls"] == 2


def test_invalid_age_header_cannot_make_old_payload_fresh(request_factory, clock):
    view, state = make_view(
        etag=True,
        response=lambda r, s: JsonResponse(
            s["value"], headers={"Age": "invalid", "Cache-Control": "max-age=300"}
        ),
    )
    assert "max-age=0" in view(request_factory.get("/products"))["Cache-Control"]
    view(request_factory.get("/products"))
    assert state["calls"] == 2


def test_bypass_keeps_a_view_policy_set_after_rendering(request_factory):
    def response(request, state):
        result = JsonTemplateResponse(None, content_type="application/json")

        def set_public(rendered):
            rendered["Cache-Control"] = "public, max-age=100"

        result.add_post_render_callback(set_public)
        return result

    view, state = make_view(etag=True, only_if=lambda r: False, response=response)
    rendered = view(request_factory.get("/products")).render()
    assert rendered["Cache-Control"] == "public, max-age=100"
    assert "ETag" not in rendered
    assert state["calls"] == 1


def test_view_etag_is_kept_as_validator(request_factory):
    view, state = make_view(
        etag=True,
        response=lambda r, s: JsonResponse(s["value"], headers={"ETag": '"v1"'}),
    )
    first = view(request_factory.get("/products"))
    assert first["ETag"] == '"v1"'
    assert (
        view(request_factory.get("/products", HTTP_IF_NONE_MATCH='"v1"')).status_code
        == 304
    )
    assert state["calls"] == 1


@pytest.mark.parametrize("policy", [None, "public", "s-maxage=60", "must-revalidate"])
def test_authorized_responses_store_only_with_shared_cache_directives(
    request_factory, policy
):
    def response(request, state):
        headers = {"Cache-Control": policy} if policy else {}
        return JsonResponse(state["value"], headers=headers)

    view, state = make_view(etag=True, response=response)
    view(request_factory.get("/products", HTTP_AUTHORIZATION="Bearer token"))
    view(request_factory.get("/products", HTTP_AUTHORIZATION="Bearer token"))
    assert state["calls"] == (2 if policy is None else 1)


def test_authorized_request_reuses_anonymous_snapshot(request_factory):
    view, state = make_view(etag=True)
    first = view(request_factory.get("/products"))
    authorized = view(
        request_factory.get("/products", HTTP_AUTHORIZATION="Bearer token")
    )
    assert authorized["ETag"] == first["ETag"]
    assert state["calls"] == 1


def test_already_compressed_response_keeps_content_encoding(request_factory):
    content = gzip.compress(b'{"name":"Product"}')
    view, state = make_view(
        etag=True,
        response=lambda r, s: HttpResponse(
            content,
            content_type="application/json",
            headers={"Content-Encoding": "gzip"},
        ),
    )
    first = view(request_factory.get("/compressed"))
    second = view(request_factory.get("/compressed"))
    assert second["Content-Encoding"] == "gzip"
    assert gzip.decompress(second.content) == b'{"name":"Product"}'
    assert second["ETag"] == first["ETag"]
    assert state["calls"] == 1
