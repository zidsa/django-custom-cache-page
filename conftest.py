import pytest
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory
from pytest_django.lazy_django import django_settings_is_configured

from custom_cache_page.cache import cache_page


@pytest.fixture(autouse=True)
def configure_django_settings():
    if not django_settings_is_configured():
        settings.configure()
        settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
        settings.CACHES = {
            "default": {
                "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                "LOCATION": "/var/tmp/cache",
            }
        }
    yield
    cache.clear()


@pytest.fixture
def request_factory():
    return RequestFactory()


# override
@pytest.fixture(scope="function", autouse=True)
def _dj_autoclear_mailbox():
    pass


@pytest.fixture
def mock_cached_view():
    @cache_page(
        timeout=1200,
        key_func=lambda r: r.path,
        versioned=False,
        group_func=lambda r: "cached_views",
        prefix="prefix",
    )
    def mocked_cached_view(request, *args, **kwargs):
        return HttpResponse(b"hi")

    return mocked_cached_view
