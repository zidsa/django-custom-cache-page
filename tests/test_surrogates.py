from django.test import RequestFactory

from custom_cache_page.surrogates import (
    SurrogateKeySet,
    surrogate_from_model,
    surrogate_from_path,
    surrogate_from_query_params,
    surrogate_from_user,
    surrogate_from_view,
)


class TestSurrogateKeySet:
    def test_add_keys(self):
        keys = SurrogateKeySet()
        keys.add("key1", "key2")
        assert "key1" in keys.keys
        assert "key2" in keys.keys

    def test_normalize_spaces(self):
        keys = SurrogateKeySet()
        keys.add("key with spaces")
        assert "key-with-spaces" in keys.keys

    def test_empty_key_ignored(self):
        keys = SurrogateKeySet()
        keys.add("")
        assert len(keys) == 0

    def test_duplicate_ignored(self):
        keys = SurrogateKeySet()
        keys.add("key1", "key1")
        assert len(keys) == 1

    def test_iter(self):
        keys = SurrogateKeySet(["a", "b"])
        assert list(keys) == ["a", "b"]

    def test_bool(self):
        assert not SurrogateKeySet()
        assert SurrogateKeySet(["key"])

    def test_to_header(self):
        keys = SurrogateKeySet(["a", "b", "c"])
        assert keys.to_header() == "a b c"

    def test_from_header(self):
        keys = SurrogateKeySet.from_header("a b c")
        assert keys.keys == ["a", "b", "c"]

    def test_from_header_empty(self):
        keys = SurrogateKeySet.from_header("")
        assert len(keys) == 0


class TestSurrogateGenerators:
    def test_surrogate_from_path(self):
        factory = RequestFactory()
        request = factory.get("/api/products/123/")
        assert surrogate_from_path(request) == "path-api-products-123"

    def test_surrogate_from_path_root(self):
        factory = RequestFactory()
        request = factory.get("/")
        assert surrogate_from_path(request) == "path-root"

    def test_surrogate_from_view(self):
        assert surrogate_from_view("product_detail") == "view-product_detail"

    def test_surrogate_from_model(self):
        assert surrogate_from_model("Product") == "model-product"

    def test_surrogate_from_model_with_pk(self):
        assert surrogate_from_model("Product", 123) == "model-product-123"

    def test_surrogate_from_user_authenticated(self):
        factory = RequestFactory()
        request = factory.get("/")

        class MockUser:
            is_authenticated = True
            pk = 42

        request.user = MockUser()
        assert surrogate_from_user(request) == "user-42"

    def test_surrogate_from_user_anonymous(self):
        factory = RequestFactory()
        request = factory.get("/")

        class MockUser:
            is_authenticated = False

        request.user = MockUser()
        assert surrogate_from_user(request) is None

    def test_surrogate_from_user_no_user(self):
        factory = RequestFactory()
        request = factory.get("/")
        assert surrogate_from_user(request) is None

    def test_surrogate_from_query_params(self):
        factory = RequestFactory()
        request = factory.get("/", {"category": "shoes", "brand": "nike"})
        keys = surrogate_from_query_params(request)
        assert "param-category-shoes" in keys
        assert "param-brand-nike" in keys

    def test_surrogate_from_query_params_specific(self):
        factory = RequestFactory()
        request = factory.get("/", {"category": "shoes", "brand": "nike"})
        keys = surrogate_from_query_params(request, params=["category"])
        assert keys == ["param-category-shoes"]

    def test_surrogate_from_query_params_empty_value(self):
        factory = RequestFactory()
        request = factory.get("/", {"category": ""})
        keys = surrogate_from_query_params(request)
        assert keys == []
