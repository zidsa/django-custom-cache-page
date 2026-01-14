from django.http import HttpResponse

from custom_cache_page import (
    Versioned,
    cache_page,
    invalidate_tag,
    invalidate_tags,
    versioned,
)
from custom_cache_page.backends.base import BaseCacheBackend
from custom_cache_page.backends.django import DjangoCacheBackend
from custom_cache_page import conf


class TestVersioned:
    def test_creates_instance(self):
        v = versioned("my-tag", timeout=1000)
        assert isinstance(v, Versioned)
        assert v.name == "my-tag"
        assert v.timeout == 1000

    def test_default_timeout(self):
        v = versioned("tag")
        assert v.timeout == 864000

    def test_accepts_callable(self):
        v = Versioned(name=lambda r: "test")
        assert callable(v.name)

    def test_resolve_name_static(self):
        v = Versioned(name="products")
        assert v.resolve_name(None) == "products"

    def test_resolve_name_callable(self, request_factory):
        v = Versioned(name=lambda r: f"store:{r.path}")
        request = request_factory.get("/test")
        assert v.resolve_name(request) == "store:/test"


class TestCachePage:
    def test_basic_caching(self, request_factory):
        call_count = 0

        @cache_page(timeout=300, key_func=lambda r: r.path)
        def view(request):
            nonlocal call_count
            call_count += 1
            return HttpResponse(b"response")

        request = request_factory.get("/basic-cache")
        view(request)
        view(request)
        assert call_count == 1

    def test_do_not_cache_bypasses(self, request_factory):
        call_count = 0

        @cache_page(timeout=300, key_func=lambda r: r.path)
        def view(request):
            nonlocal call_count
            call_count += 1
            return HttpResponse(b"response")

        request = request_factory.get("/no-cache")
        request.do_not_cache = True
        view(request)
        view(request)
        assert call_count == 2

    def test_only_if_false_bypasses(self, request_factory):
        call_count = 0

        @cache_page(timeout=300, key_func=lambda r: r.path, only_if=lambda r: False)
        def view(request):
            nonlocal call_count
            call_count += 1
            return HttpResponse(b"response")

        request = request_factory.get("/only-if-false")
        view(request)
        view(request)
        assert call_count == 2

    def test_only_if_true_caches(self, request_factory):
        call_count = 0

        @cache_page(timeout=300, key_func=lambda r: r.path, only_if=lambda r: True)
        def view(request):
            nonlocal call_count
            call_count += 1
            return HttpResponse(b"response")

        request = request_factory.get("/only-if-true")
        view(request)
        view(request)
        assert call_count == 1

    def test_non_200_not_cached(self, request_factory):
        call_count = 0

        @cache_page(timeout=300, key_func=lambda r: r.path)
        def view(request):
            nonlocal call_count
            call_count += 1
            return HttpResponse(b"not found", status=404)

        request = request_factory.get("/404")
        view(request)
        view(request)
        assert call_count == 2

    def test_bust_cache_attribute(self, request_factory):
        call_count = 0

        @cache_page(timeout=300, key_func=lambda r: r.path)
        def view(request):
            nonlocal call_count
            call_count += 1
            return HttpResponse(b"response")

        request = request_factory.get("/bust")
        view(request)

        request2 = request_factory.get("/bust")
        request2._bust_cache = True
        view(request2)
        assert call_count == 2

    def test_backend_as_string(self, request_factory, settings):
        settings.CUSTOM_CACHE_PAGE = {
            "BACKENDS": {
                "test": {"BACKEND": "django", "OPTIONS": {"cache_name": "default"}}
            }
        }
        conf.clear_backend_cache()

        @cache_page(timeout=300, key_func=lambda r: r.path, backend="test")
        def view(request):
            return HttpResponse(b"response")

        request = request_factory.get("/backend-string")
        response = view(request)
        assert response.status_code == 200

    def test_backend_as_instance(self, request_factory):
        backend = DjangoCacheBackend(cache_name="default")

        @cache_page(timeout=300, key_func=lambda r: r.path, backend=backend)
        def view(request):
            return HttpResponse(b"response")

        request = request_factory.get("/backend-instance")
        response = view(request)
        assert response.status_code == 200

    def test_prefix_callable(self, request_factory):
        call_count = 0

        @cache_page(
            timeout=300,
            key_func=lambda r: "key",
            prefix=lambda r: f"store:{r.GET.get('store', '1')}",
        )
        def view(request):
            nonlocal call_count
            call_count += 1
            return HttpResponse(b"response")

        req1 = request_factory.get("/test?store=1")
        req2 = request_factory.get("/test?store=2")

        view(req1)
        view(req1)
        assert call_count == 1

        view(req2)
        assert call_count == 2

    def test_timeout_callable(self, request_factory):
        @cache_page(
            timeout=lambda resp: 600 if resp.status_code == 200 else 60,
            key_func=lambda r: r.path,
        )
        def view(request):
            return HttpResponse(b"response")

        request = request_factory.get("/timeout-callable")
        response = view(request)
        assert response.status_code == 200
        assert "max-age=600" in response.get("Cache-Control", "")


class TestCachePageTags:
    def test_static_tags(self, request_factory):
        @cache_page(timeout=300, key_func=lambda r: r.path, tags=["products"])
        def view(request):
            return HttpResponse(b"response")

        request = request_factory.get("/static-tags")
        response = view(request)
        assert response.status_code == 200

    def test_versioned_tag(self, request_factory):
        @cache_page(
            timeout=300, key_func=lambda r: r.path, tags=[versioned("products")]
        )
        def view(request):
            return HttpResponse(b"response")

        request = request_factory.get("/versioned-tags")
        response = view(request)
        assert response.status_code == 200

    def test_dynamic_versioned_tag(self, request_factory):
        call_count = 0

        @cache_page(
            timeout=300,
            key_func=lambda r: "key",
            tags=[versioned(lambda r: f"store:{r.GET.get('store', '1')}")],
        )
        def view(request):
            nonlocal call_count
            call_count += 1
            return HttpResponse(b"response")

        req1 = request_factory.get("/test?store=1")
        req2 = request_factory.get("/test?store=2")

        view(req1)
        view(req1)
        assert call_count == 1

        view(req2)
        assert call_count == 2

    def test_callable_returning_string(self, request_factory):
        @cache_page(
            timeout=300, key_func=lambda r: r.path, tags=[lambda r: "dynamic-tag"]
        )
        def view(request):
            return HttpResponse(b"response")

        request = request_factory.get("/callable-string")
        response = view(request)
        assert response.status_code == 200

    def test_callable_returning_list(self, request_factory):
        @cache_page(
            timeout=300, key_func=lambda r: r.path, tags=[lambda r: ["tag1", "tag2"]]
        )
        def view(request):
            return HttpResponse(b"response")

        request = request_factory.get("/callable-list")
        response = view(request)
        assert response.status_code == 200

    def test_callable_returning_none(self, request_factory):
        @cache_page(timeout=300, key_func=lambda r: r.path, tags=[lambda r: None])
        def view(request):
            return HttpResponse(b"response")

        request = request_factory.get("/callable-none")
        response = view(request)
        assert response.status_code == 200


class DeferredResponse(HttpResponse):
    def __init__(self):
        super().__init__(b"deferred")
        self._callbacks = []

    def render(self):
        for cb in self._callbacks:
            cb(self)
        return self

    def add_post_render_callback(self, callback):
        self._callbacks.append(callback)


class TestCachePageDeferredResponse:
    def test_post_render_callback_registered(self, request_factory):
        @cache_page(timeout=300, key_func=lambda r: r.path)
        def view(request):
            return DeferredResponse()

        request = request_factory.get("/deferred-reg")
        response = view(request)
        assert len(response._callbacks) == 1

    def test_post_render_callback_executed(self, request_factory):
        class MemoryBackend(BaseCacheBackend):
            def __init__(self):
                super().__init__()
                self.stored = {}

            def get(self, key):
                return self.stored.get(key)

            def set(self, entry):
                self.stored[entry.key] = entry.response

            def delete(self, key):
                return self.stored.pop(key, None) is not None

            def invalidate_by_surrogate(self, key):
                return 0

        backend = MemoryBackend()

        @cache_page(timeout=300, key_func=lambda r: r.path, backend=backend)
        def view(request):
            return DeferredResponse()

        request = request_factory.get("/deferred-exec")
        response = view(request)
        response.render()

        assert len(backend.stored) == 1


class TestInvalidation:
    def test_invalidate_tag(self, request_factory):
        @cache_page(timeout=300, key_func=lambda r: r.path, tags=["inv-tag"])
        def view(request):
            return HttpResponse(b"response")

        request = request_factory.get("/inv-test")
        view(request)
        result = invalidate_tag("inv-tag")
        assert result >= 0

    def test_invalidate_tags(self, request_factory):
        @cache_page(timeout=300, key_func=lambda r: r.path, tags=["tag-a", "tag-b"])
        def view(request):
            return HttpResponse(b"response")

        request = request_factory.get("/inv-multi")
        view(request)
        result = invalidate_tags(["tag-a", "tag-b"])
        assert result >= 0

    def test_invalidate_versioned_tag(self, request_factory):
        @cache_page(timeout=300, key_func=lambda r: r.path, tags=[versioned("v-group")])
        def view(request):
            return HttpResponse(b"response")

        request = request_factory.get("/v-inv")
        view(request)
        result = invalidate_tag("v-group")
        assert result >= 1

    def test_falls_back_to_surrogate(self):
        class NoVersionBackend(BaseCacheBackend):
            def __init__(self):
                super().__init__()
                self.invalidated = []

            def get(self, key):
                return None

            def set(self, entry):
                pass

            def delete(self, key):
                return False

            def invalidate_by_surrogate(self, key):
                self.invalidated.append(key)
                return 1

        backend = NoVersionBackend()
        conf._backend_cache["no-version"] = backend

        result = invalidate_tag("test-tag", backend="no-version")
        assert result == 1
        assert "test-tag" in backend.invalidated

        del conf._backend_cache["no-version"]

    def test_invalidate_tags_falls_back(self):
        class NoVersionBackend(BaseCacheBackend):
            def __init__(self):
                super().__init__()
                self.invalidated = []

            def get(self, key):
                return None

            def set(self, entry):
                pass

            def delete(self, key):
                return False

            def invalidate_by_surrogate(self, key):
                self.invalidated.append(key)
                return 1

        backend = NoVersionBackend()
        conf._backend_cache["no-version-batch"] = backend

        result = invalidate_tags(["a", "b"], backend="no-version-batch")
        assert result == 2
        assert "a" in backend.invalidated
        assert "b" in backend.invalidated

        del conf._backend_cache["no-version-batch"]
