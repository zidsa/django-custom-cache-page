from django.http import HttpResponse
from django.core.cache import cache
from custom_cache_page.utils import hash_key


class TestCache:
    def test_cache_page(self, request_factory, mock_cached_view):
        request = request_factory.get('/bo')
        mock_cached_view(request)
        cached_response = cache.get(hash_key('prefix:cached_views:0:/bo'))
        assert cached_response
        assert type(cached_response) == HttpResponse
        assert cached_response.content == HttpResponse('hi').content
