from django.test import RequestFactory

from custom_cache_page import (
    generate_cache_key,
    generate_query_params_cache_key,
    hash_key,
)


class TestKeyGeneration:
    def test_generate_query_params_cache_key(self):
        factory = RequestFactory()
        request = factory.get("/path", {"page": "1", "size": "10"})
        key = generate_query_params_cache_key(request)
        assert "page:1" in key
        assert "size:10" in key

    def test_generate_query_params_cache_key_sorted(self):
        factory = RequestFactory()
        request = factory.get("/path", {"z": "1", "a": "2"})
        key = generate_query_params_cache_key(request)
        assert key.index("a:2") < key.index("z:1")

    def test_generate_cache_key(self):
        factory = RequestFactory()
        request = factory.get("/my-path", {"page": "1"})
        key = generate_cache_key(request)
        assert "page:1" in key
        assert "mypath" in key

    def test_hash_key(self):
        key = hash_key("test-key")
        assert len(key) == 32
        assert key == hash_key("test-key")
