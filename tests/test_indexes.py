import pytest
from unittest.mock import MagicMock, patch
from django.core.cache import cache

from custom_cache_page.indexes import (
    BaseSurrogateIndex,
    DjangoCacheIndex,
    NullSurrogateIndex,
    RedisSurrogateIndex,
)


class TestDjangoCacheIndex:
    def test_add_and_get(self):
        index = DjangoCacheIndex(cache=cache, timeout=300)
        index.add("products", "key1")
        index.add("products", "key2")

        keys = index.get_keys("products")
        assert "key1" in keys
        assert "key2" in keys

    def test_get_empty(self):
        index = DjangoCacheIndex(cache=cache, timeout=300)
        keys = index.get_keys("nonexistent")
        assert keys == set()

    def test_remove(self):
        index = DjangoCacheIndex(cache=cache, timeout=300)
        index.add("removable", "key1")
        assert len(index.get_keys("removable")) == 1

        index.remove("removable")
        assert len(index.get_keys("removable")) == 0

    def test_custom_prefix(self):
        index = DjangoCacheIndex(cache=cache, timeout=300, prefix="_custom:")
        assert index._index_key("test") == "_custom:test"

    def test_auto_detects_redis_client(self):
        mock_redis = MagicMock()
        mock_redis.sadd = MagicMock()
        mock_redis.smembers = MagicMock()

        mock_cache = MagicMock()
        mock_cache._cache.get_client.return_value = mock_redis

        index = DjangoCacheIndex(cache=mock_cache, timeout=300)
        assert index._redis_client == mock_redis

    def test_uses_redis_sadd_when_available(self):
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_redis.sadd = MagicMock()
        mock_redis.smembers = MagicMock()

        mock_cache = MagicMock()
        mock_cache._cache.get_client.return_value = mock_redis

        index = DjangoCacheIndex(cache=mock_cache, timeout=300)
        index.add("products", "key1")

        mock_pipe.sadd.assert_called_once()
        mock_pipe.expire.assert_called_once()
        mock_pipe.execute.assert_called_once()

    def test_uses_redis_smembers_when_available(self):
        mock_redis = MagicMock()
        mock_redis.sadd = MagicMock()
        mock_redis.smembers.return_value = {b"key1", b"key2"}

        mock_cache = MagicMock()
        mock_cache._cache.get_client.return_value = mock_redis

        index = DjangoCacheIndex(cache=mock_cache, timeout=300)
        keys = index.get_keys("products")

        assert keys == {"key1", "key2"}
        mock_redis.smembers.assert_called_once()

    def test_uses_redis_delete_when_available(self):
        mock_redis = MagicMock()
        mock_redis.sadd = MagicMock()
        mock_redis.smembers = MagicMock()

        mock_cache = MagicMock()
        mock_cache._cache.get_client.return_value = mock_redis

        index = DjangoCacheIndex(cache=mock_cache, timeout=300)
        index.remove("products")

        mock_redis.delete.assert_called_once()

    def test_fallback_when_no_redis_detected(self):
        mock_cache = MagicMock()
        mock_cache._cache = None
        mock_cache.client = None

        index = DjangoCacheIndex(cache=mock_cache, timeout=300)
        assert index._redis_client is None

    def test_fallback_when_detection_fails(self):
        mock_cache = MagicMock()
        mock_cache._cache.get_client.side_effect = Exception("Not available")

        index = DjangoCacheIndex(cache=mock_cache, timeout=300)
        assert index._redis_client is None

    def test_fallback_when_client_lacks_redis_methods(self):
        mock_client = MagicMock(spec=[])

        mock_cache = MagicMock()
        mock_cache._cache.get_client.return_value = mock_client

        index = DjangoCacheIndex(cache=mock_cache, timeout=300)
        assert index._redis_client is None

    def test_respects_key_prefix_with_redis(self):
        mock_redis = MagicMock()
        mock_redis.sadd = MagicMock()
        mock_redis.smembers = MagicMock()

        mock_cache = MagicMock()
        mock_cache._cache.get_client.return_value = mock_redis
        mock_cache.key_prefix = "myapp:"

        index = DjangoCacheIndex(cache=mock_cache, timeout=300)
        assert index._cache_prefix == "myapp:"
        assert index._index_key("products") == "myapp:_surrogate:products"

    def test_key_prefix_from_cache_client(self):
        mock_redis = MagicMock()
        mock_redis.sadd = MagicMock()
        mock_redis.smembers = MagicMock()

        mock_cache = MagicMock()
        mock_cache._cache.get_client.return_value = mock_redis
        mock_cache.key_prefix = None
        mock_cache._cache._prefix = "v2:"

        index = DjangoCacheIndex(cache=mock_cache, timeout=300)
        assert index._cache_prefix == "v2:"
        assert index._index_key("products") == "v2:_surrogate:products"

    def test_no_prefix_when_not_using_redis(self):
        mock_cache = MagicMock()
        mock_cache._cache = None
        mock_cache.client = None
        mock_cache.key_prefix = "myapp:"

        index = DjangoCacheIndex(cache=mock_cache, timeout=300)
        assert index._cache_prefix == ""
        assert index._index_key("products") == "_surrogate:products"

    def test_key_prefix_exception_handling(self):
        mock_redis = MagicMock()
        mock_redis.sadd = MagicMock()
        mock_redis.smembers = MagicMock()

        mock_cache = MagicMock()
        mock_cache._cache.get_client.return_value = mock_redis

        type(mock_cache).key_prefix = property(
            lambda self: (_ for _ in ()).throw(Exception("boom"))
        )

        index = DjangoCacheIndex(cache=mock_cache, timeout=300)
        assert index._cache_prefix == ""


class TestNullSurrogateIndex:
    def test_add_is_noop(self):
        index = NullSurrogateIndex()
        index.add("products", "key1")

    def test_get_returns_empty(self):
        index = NullSurrogateIndex()
        assert index.get_keys("products") == set()

    def test_remove_is_noop(self):
        index = NullSurrogateIndex()
        index.remove("products")


class TestRedisSurrogateIndex:
    def test_requires_client_or_url(self):
        with pytest.raises(ValueError, match="Either redis_client or url"):
            RedisSurrogateIndex()

    def test_with_client(self):
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe

        index = RedisSurrogateIndex(redis_client=mock_redis, timeout=300)
        index.add("products", "key1")

        mock_pipe.sadd.assert_called_once()
        mock_pipe.expire.assert_called_once()
        mock_pipe.execute.assert_called_once()

    def test_get_keys(self):
        mock_redis = MagicMock()
        mock_redis.smembers.return_value = {b"key1", b"key2"}

        index = RedisSurrogateIndex(redis_client=mock_redis)
        keys = index.get_keys("products")

        assert keys == {"key1", "key2"}

    def test_get_keys_string_members(self):
        mock_redis = MagicMock()
        mock_redis.smembers.return_value = {"key1", "key2"}

        index = RedisSurrogateIndex(redis_client=mock_redis)
        keys = index.get_keys("products")

        assert keys == {"key1", "key2"}

    def test_remove(self):
        mock_redis = MagicMock()
        index = RedisSurrogateIndex(redis_client=mock_redis)

        index.remove("products")
        mock_redis.delete.assert_called_once()

    def test_create_client_from_url(self):
        mock_redis_module = MagicMock()
        mock_client = MagicMock()
        mock_redis_module.from_url.return_value = mock_client

        with patch.dict("sys.modules", {"redis": mock_redis_module}):
            index = RedisSurrogateIndex(url="redis://localhost:6379/0")
            assert index.redis == mock_client
            mock_redis_module.from_url.assert_called_once_with(
                "redis://localhost:6379/0"
            )

    def test_import_error(self):
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "redis":
                raise ImportError("No module named 'redis'")
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", mock_import):
            with pytest.raises(ImportError, match="redis-py is required"):
                RedisSurrogateIndex(url="redis://localhost:6379/0")


class TestDjangoCacheBackendWithIndex:
    def test_uses_custom_index(self):
        from custom_cache_page.backends.django import DjangoCacheBackend
        from custom_cache_page.backends.base import CacheEntry
        from django.http import HttpResponse

        mock_index = MagicMock(spec=BaseSurrogateIndex)
        backend = DjangoCacheBackend(cache_name="default", surrogate_index=mock_index)

        entry = CacheEntry(
            key="test-key",
            response=HttpResponse(b"test"),
            timeout=300,
            surrogate_keys=["products"],
        )
        backend.set(entry)

        mock_index.add.assert_called_once_with("products", "test-key")

    def test_lazy_creates_default_index(self):
        from custom_cache_page.backends.django import DjangoCacheBackend

        backend = DjangoCacheBackend(cache_name="default")
        index = backend.surrogate_index

        assert isinstance(index, DjangoCacheIndex)

    def test_invalidate_uses_index(self):
        from custom_cache_page.backends.django import DjangoCacheBackend

        mock_index = MagicMock(spec=BaseSurrogateIndex)
        mock_index.get_keys.return_value = {"key1", "key2"}

        backend = DjangoCacheBackend(cache_name="default", surrogate_index=mock_index)
        backend.invalidate_by_surrogate("products")

        mock_index.get_keys.assert_called_once_with("products")
        mock_index.remove.assert_called_once_with("products")
