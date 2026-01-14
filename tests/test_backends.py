import pytest
from django.http import HttpResponse

from custom_cache_page.backends.base import (
    BaseCacheBackend,
    CacheEntry,
    HeaderAwareMixin,
)
from custom_cache_page.backends.composite import CompositeBackend
from custom_cache_page.backends.django import DjangoCacheBackend


class TestDjangoCacheBackend:
    def test_get_set(self):
        backend = DjangoCacheBackend(cache_name="default")
        response = HttpResponse(b"test content")
        entry = CacheEntry(
            key="test-key",
            response=response,
            timeout=300,
            surrogate_keys=["tag1", "tag2"],
        )
        backend.set(entry)

        cached = backend.get("test-key")
        assert cached is not None
        assert cached.content == b"test content"

    def test_delete(self):
        backend = DjangoCacheBackend(cache_name="default")
        entry = CacheEntry(
            key="delete-key", response=HttpResponse(b"test"), timeout=300
        )
        backend.set(entry)

        assert backend.get("delete-key") is not None
        backend.delete("delete-key")
        assert backend.get("delete-key") is None

    def test_surrogate_key_index(self):
        backend = DjangoCacheBackend(cache_name="default")
        entry1 = CacheEntry(
            key="key1",
            response=HttpResponse(b"1"),
            timeout=300,
            surrogate_keys=["products"],
        )
        entry2 = CacheEntry(
            key="key2",
            response=HttpResponse(b"2"),
            timeout=300,
            surrogate_keys=["products"],
        )
        backend.set(entry1)
        backend.set(entry2)

        assert backend.get("key1") is not None
        assert backend.get("key2") is not None

        count = backend.invalidate_by_surrogate("products")
        assert count == 2
        assert backend.get("key1") is None
        assert backend.get("key2") is None

    def test_invalidate_empty_surrogate(self):
        backend = DjangoCacheBackend(cache_name="default")
        result = backend.invalidate_by_surrogate("nonexistent")
        assert result == 0

    def test_group_versioning(self):
        backend = DjangoCacheBackend(cache_name="default")

        v1 = backend.get_group_version("test-group", timeout=300)
        assert v1 == 1

        v2 = backend.increment_group_version("test-group")
        assert v2 == 2

        v3 = backend.get_group_version("test-group", timeout=300)
        assert v3 == 2

    def test_prepare_response_unchanged(self):
        backend = DjangoCacheBackend(cache_name="default")
        response = HttpResponse(b"test")
        prepared = backend.prepare_response(response, ["tag1", "tag2"])
        assert prepared is response

    def test_serializes_headers(self):
        backend = DjangoCacheBackend(cache_name="default")
        response = HttpResponse(b"test content", content_type="application/json")
        response["Cache-Control"] = "max-age=3600"
        response["ETag"] = '"abc123"'

        entry = CacheEntry(key="headers-key", response=response, timeout=300)
        backend.set(entry)

        cached = backend.get("headers-key")
        assert cached is not None
        assert cached.content == b"test content"
        assert cached["Content-Type"] == "application/json"
        assert cached["Cache-Control"] == "max-age=3600"
        assert cached["ETag"] == '"abc123"'

    def test_get_nonexistent_returns_none(self):
        backend = DjangoCacheBackend(cache_name="default")
        assert backend.get("does-not-exist-xyz") is None


class TestBaseCacheBackend:
    def test_invalidate_by_surrogates_default(self):
        backend = DjangoCacheBackend(cache_name="default")
        result = backend.invalidate_by_surrogates(["key1", "key2"])
        assert result == 0

    def test_get_group_version_not_implemented(self):
        class MinimalBackend(BaseCacheBackend):
            def get(self, key):
                return None

            def set(self, entry):
                pass

            def delete(self, key):
                return False

            def invalidate_by_surrogate(self, key):
                return 0

        backend = MinimalBackend()
        with pytest.raises(NotImplementedError):
            backend.get_group_version("group", 300)

    def test_increment_group_version_not_implemented(self):
        class MinimalBackend(BaseCacheBackend):
            def get(self, key):
                return None

            def set(self, entry):
                pass

            def delete(self, key):
                return False

            def invalidate_by_surrogate(self, key):
                return 0

        backend = MinimalBackend()
        with pytest.raises(NotImplementedError):
            backend.increment_group_version("group")


class TestHeaderAwareMixin:
    def test_add_surrogate_headers(self):
        class TestBackend(HeaderAwareMixin):
            pass

        backend = TestBackend()
        response = HttpResponse(b"test")
        result = backend.add_surrogate_headers(response, ["key1", "key2"])
        assert result["Surrogate-Key"] == "key1 key2"

    def test_add_surrogate_headers_empty(self):
        class TestBackend(HeaderAwareMixin):
            pass

        backend = TestBackend()
        response = HttpResponse(b"test")
        result = backend.add_surrogate_headers(response, [])
        assert "Surrogate-Key" not in result

    def test_key_too_large(self):
        class TestBackend(HeaderAwareMixin):
            MAX_KEY_SIZE = 10

        backend = TestBackend()
        response = HttpResponse(b"test")
        result = backend.add_surrogate_headers(
            response, ["short", "this-key-is-way-too-long"]
        )
        assert result["Surrogate-Key"] == "short"

    def test_header_size_limit(self):
        class TestBackend(HeaderAwareMixin):
            MAX_HEADER_SIZE = 15

        backend = TestBackend()
        response = HttpResponse(b"test")
        result = backend.add_surrogate_headers(response, ["abc", "def", "ghi", "jkl"])
        header = result.get("Surrogate-Key", "")
        assert len(header.encode("utf-8")) <= 15


class TestCompositeBackend:
    def test_get_from_primary(self):
        backend1 = DjangoCacheBackend(cache_name="default")
        backend2 = DjangoCacheBackend(cache_name="default")
        entry = CacheEntry(
            key="composite-get", response=HttpResponse(b"test"), timeout=300
        )
        backend1.set(entry)

        composite = CompositeBackend(backends=[backend1, backend2])
        result = composite.get("composite-get")
        assert result is not None

    def test_get_miss(self):
        backend = DjangoCacheBackend(cache_name="default")
        composite = CompositeBackend(backends=[backend])
        result = composite.get("nonexistent")
        assert result is None

    def test_get_invalid_read_from(self):
        backend = DjangoCacheBackend(cache_name="default")
        composite = CompositeBackend(backends=[backend], read_from=999)
        result = composite.get("any-key")
        assert result is None

    def test_set_all_backends(self):
        backend1 = DjangoCacheBackend(cache_name="default")
        backend2 = DjangoCacheBackend(cache_name="default")
        composite = CompositeBackend(backends=[backend1, backend2])

        entry = CacheEntry(
            key="composite-set", response=HttpResponse(b"test"), timeout=300
        )
        composite.set(entry)

        assert backend1.get("composite-set") is not None
        assert backend2.get("composite-set") is not None

    def test_delete(self):
        backend = DjangoCacheBackend(cache_name="default")
        composite = CompositeBackend(backends=[backend])
        entry = CacheEntry(
            key="composite-delete", response=HttpResponse(b"test"), timeout=300
        )
        composite.set(entry)

        result = composite.delete("composite-delete")
        assert result is True

    def test_delete_no_hits(self):
        backend = DjangoCacheBackend(cache_name="default")
        composite = CompositeBackend(backends=[backend])
        result = composite.delete("nonexistent")
        assert result is False

    def test_invalidate_by_surrogate(self):
        backend = DjangoCacheBackend(cache_name="default")
        composite = CompositeBackend(backends=[backend])
        entry = CacheEntry(
            key="comp-inv",
            response=HttpResponse(b"test"),
            timeout=300,
            surrogate_keys=["comp-tag"],
        )
        composite.set(entry)

        result = composite.invalidate_by_surrogate("comp-tag")
        assert result >= 1

    def test_invalidate_by_surrogates(self):
        backend = DjangoCacheBackend(cache_name="default")
        composite = CompositeBackend(backends=[backend])
        result = composite.invalidate_by_surrogates(["tag1", "tag2"])
        assert result >= 0

    def test_prepare_response_chains(self):
        class HeaderBackend(HeaderAwareMixin, BaseCacheBackend):
            def get(self, key):
                return None

            def set(self, entry):
                pass

            def delete(self, key):
                return False

            def invalidate_by_surrogate(self, key):
                return 0

            def prepare_response(self, response, keys):
                return self.add_surrogate_headers(response, keys)

        backend1 = HeaderBackend()
        backend2 = DjangoCacheBackend(cache_name="default")
        composite = CompositeBackend(backends=[backend1, backend2])

        response = HttpResponse(b"test")
        result = composite.prepare_response(response, ["key1", "key2"])
        assert result["Surrogate-Key"] == "key1 key2"

    def test_get_group_version(self):
        backend = DjangoCacheBackend(cache_name="default")
        composite = CompositeBackend(backends=[backend])
        version = composite.get_group_version("comp-group", 300)
        assert version >= 1

    def test_get_group_version_no_support(self):
        class NoVersionBackend(BaseCacheBackend):
            def get(self, key):
                return None

            def set(self, entry):
                pass

            def delete(self, key):
                return False

            def invalidate_by_surrogate(self, key):
                return 0

        composite = CompositeBackend(backends=[NoVersionBackend()])
        with pytest.raises(NotImplementedError, match="No backend supports"):
            composite.get_group_version("group", 300)

    def test_increment_group_version(self):
        backend = DjangoCacheBackend(cache_name="default")
        composite = CompositeBackend(backends=[backend])
        composite.get_group_version("comp-inc", 300)
        new_version = composite.increment_group_version("comp-inc")
        assert new_version >= 2

    def test_increment_group_version_no_support(self):
        class NoVersionBackend(BaseCacheBackend):
            def get(self, key):
                return None

            def set(self, entry):
                pass

            def delete(self, key):
                return False

            def invalidate_by_surrogate(self, key):
                return 0

        composite = CompositeBackend(backends=[NoVersionBackend()])
        with pytest.raises(NotImplementedError, match="No backend supports"):
            composite.increment_group_version("group")

    def test_increment_skips_unsupported(self):
        class NoVersionBackend(BaseCacheBackend):
            def get(self, key):
                return None

            def set(self, entry):
                pass

            def delete(self, key):
                return False

            def invalidate_by_surrogate(self, key):
                return 0

        backend1 = NoVersionBackend()
        backend2 = DjangoCacheBackend(cache_name="default")
        composite = CompositeBackend(backends=[backend1, backend2])

        composite.get_group_version("skip-test", 300)
        version = composite.increment_group_version("skip-test")
        assert version >= 2
