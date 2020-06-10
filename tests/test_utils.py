from django.core.cache import cache

from custom_cache_page.utils import generate_query_params_cache_key, generate_cache_key, invalidate_group_caches


class TestUtils:
    def test_generate_query_params_cache_key(self, request_factory):
        request = request_factory.get('/boo', {'page': 1, 'page_size': 100})
        key = generate_query_params_cache_key(request)
        assert type(key) == str
        assert 'page' in key
        assert 'page_size' in key
        assert 'boo' not in key

    def test_generate_cache_key(self, request_factory):
        request = request_factory.get('/boo', {'page': 2, 'page_size': 450})
        key = generate_cache_key(request)
        assert type(key) == str
        assert 'page' in key
        assert 'page_size' in key
        assert 'boo' in key

    def test_invalidate_group_caches(self):
        group_version = cache.set('cached_views', 1)
        invalidate_group_caches(group_version)
        new_group_version = cache.get('cached_views')
        assert group_version != new_group_version
