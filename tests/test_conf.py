import pytest

from custom_cache_page.backends.composite import CompositeBackend
from custom_cache_page.backends.django import DjangoCacheBackend
from custom_cache_page.conf import (
    clear_backend_cache,
    get_backend_by_name,
    get_backend_class,
    get_default_backend,
)


class TestGetBackendClass:
    def test_builtin_name(self):
        cls = get_backend_class("django")
        assert cls == DjangoCacheBackend

    def test_dotted_path(self):
        cls = get_backend_class("custom_cache_page.backends.django.DjangoCacheBackend")
        assert cls == DjangoCacheBackend


class TestGetBackendByName:
    def test_creates_backend(self, settings):
        settings.CUSTOM_CACHE_PAGE = {
            "BACKENDS": {
                "mybackend": {
                    "BACKEND": "django",
                    "OPTIONS": {"cache_name": "default"},
                }
            }
        }
        clear_backend_cache()

        backend = get_backend_by_name("mybackend")
        assert isinstance(backend, DjangoCacheBackend)

    def test_caches_backend(self, settings):
        settings.CUSTOM_CACHE_PAGE = {
            "BACKENDS": {
                "cached": {"BACKEND": "django", "OPTIONS": {"cache_name": "default"}}
            }
        }
        clear_backend_cache()

        backend1 = get_backend_by_name("cached")
        backend2 = get_backend_by_name("cached")
        assert backend1 is backend2

    def test_unknown_raises(self, settings):
        settings.CUSTOM_CACHE_PAGE = {"BACKENDS": {}}
        clear_backend_cache()

        with pytest.raises(ValueError, match="Unknown cache backend"):
            get_backend_by_name("unknown")

    def test_composite_resolves_backends(self, settings):
        settings.CUSTOM_CACHE_PAGE = {
            "BACKENDS": {
                "b1": {"BACKEND": "django", "OPTIONS": {"cache_name": "default"}},
                "comp": {"BACKEND": "composite", "OPTIONS": {"backends": ["b1"]}},
            }
        }
        clear_backend_cache()

        backend = get_backend_by_name("comp")
        assert isinstance(backend, CompositeBackend)


class TestGetDefaultBackend:
    def test_from_settings(self, settings):
        settings.CUSTOM_CACHE_PAGE = {
            "DEFAULT_BACKEND": "mydefault",
            "BACKENDS": {
                "mydefault": {
                    "BACKEND": "django",
                    "OPTIONS": {"cache_name": "default"},
                }
            },
        }
        clear_backend_cache()

        backend = get_default_backend()
        assert isinstance(backend, DjangoCacheBackend)

    def test_fallback(self, settings):
        settings.CUSTOM_CACHE_PAGE = {}
        clear_backend_cache()

        backend = get_default_backend()
        assert isinstance(backend, DjangoCacheBackend)


class TestClearBackendCache:
    def test_clears_cache(self, settings):
        settings.CUSTOM_CACHE_PAGE = {
            "BACKENDS": {
                "toclear": {
                    "BACKEND": "django",
                    "OPTIONS": {"cache_name": "default"},
                }
            }
        }
        clear_backend_cache()

        get_backend_by_name("toclear")
        clear_backend_cache()
        backend = get_backend_by_name("toclear")
        assert isinstance(backend, DjangoCacheBackend)
