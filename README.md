A flexible implementation of Django's [`cache_page`](https://docs.djangoproject.com/en/dev/topics/cache/#the-per-view-cache) decorator.

# Description

This package provides two default ways to generate cache keys:
- generate_cache_key: similar to Django's default
- generate_query_params_cache_key

And allows you to define your custom key generation functions.



# Installation
 
```bash
pip install django-custom-cache-page
```

# Example


views.py:

```python
from django.http import HttpResponse

from custom_cache_page.cache import cache_page
from custom_cache_page.utils import generate_query_params_cache_key

@cache_page(60 * 60, generate_query_params_cache_key)
def my_view(request):
    return HttpResponse("okay")
```

---

## Development installation

```bash
git clone https://github.com/zidsa/django-custom-cache-page.git
cd django-custom-cache-page
pip install --editable .
```