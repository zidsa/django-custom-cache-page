"""
Integration tests for surrogate indexes with actual Redis.

These tests require a running Redis server at localhost:6379.
They are skipped if Redis is not available.
"""

import pytest

try:
    import redis

    redis_available = True
except ImportError:
    redis_available = False


def get_redis_client():
    """Try to connect to Redis and return client if available."""
    if not redis_available:
        return None
    try:
        client = redis.from_url("redis://localhost:6379/15")
        client.ping()
        return client
    except redis.ConnectionError:
        return None


@pytest.fixture
def redis_client():
    """Fixture that provides a Redis client or skips test."""
    client = get_redis_client()
    if client is None:
        pytest.skip("Redis not available at localhost:6379")
    yield client
    client.flushdb()


class TestRedisSurrogateIndexIntegration:
    def test_add_and_get_real_redis(self, redis_client):
        from custom_cache_page.indexes import RedisSurrogateIndex

        index = RedisSurrogateIndex(redis_client=redis_client, prefix="_test:")

        index.add("products", "cache-key-1")
        index.add("products", "cache-key-2")
        index.add("products", "cache-key-1")

        keys = index.get_keys("products")
        assert keys == {"cache-key-1", "cache-key-2"}

    def test_remove_real_redis(self, redis_client):
        from custom_cache_page.indexes import RedisSurrogateIndex

        index = RedisSurrogateIndex(redis_client=redis_client, prefix="_test:")

        index.add("removable", "key1")
        index.add("removable", "key2")
        assert len(index.get_keys("removable")) == 2

        index.remove("removable")
        assert index.get_keys("removable") == set()

    def test_concurrent_adds_are_atomic(self, redis_client):
        """Verify concurrent adds work correctly."""
        from concurrent.futures import ThreadPoolExecutor

        from custom_cache_page.indexes import RedisSurrogateIndex

        index = RedisSurrogateIndex(redis_client=redis_client, prefix="_test:")

        def add_keys(start):
            for i in range(100):
                index.add("concurrent", f"key-{start + i}")

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(add_keys, i * 100) for i in range(4)]
            for f in futures:
                f.result()

        keys = index.get_keys("concurrent")
        assert len(keys) == 400

    def test_expiration(self, redis_client):
        from custom_cache_page.indexes import RedisSurrogateIndex

        index = RedisSurrogateIndex(
            redis_client=redis_client, prefix="_test:", timeout=2
        )

        index.add("expiring", "key1")

        ttl = redis_client.ttl("_test:expiring")
        assert 0 < ttl <= 2


class TestDjangoCacheIndexWithRedisIntegration:
    def test_auto_detection_with_real_django_redis(self, redis_client):
        """Test DjangoCacheIndex auto-detects redis-py client."""
        from custom_cache_page.indexes import DjangoCacheIndex

        class MockDjangoRedisCache:
            def __init__(self, redis_client):
                self._cache = MockCacheClient(redis_client)

            def get(self, key, default=None):
                return default

            def set(self, key, value, timeout=None):
                pass

            def delete(self, key):
                pass

        class MockCacheClient:
            def __init__(self, redis_client):
                self._redis_client = redis_client

            def get_client(self):
                return self._redis_client

        mock_cache = MockDjangoRedisCache(redis_client)
        index = DjangoCacheIndex(cache=mock_cache, prefix="_test:")

        assert index._redis_client is not None

        index.add("products", "key1")
        index.add("products", "key2")

        keys = index.get_keys("products")
        assert keys == {"key1", "key2"}

        index.remove("products")
        assert index.get_keys("products") == set()
