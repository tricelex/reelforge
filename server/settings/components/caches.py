# Caching
# https://docs.djangoproject.com/en/6.0/topics/cache/

from server.settings.components import config

REDIS_URL: str = config('REDIS_URL', default='redis://localhost:6379/0')
REDIS_CACHE_URL: str = config('REDIS_CACHE_URL', default='redis://localhost:6379/1')

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_CACHE_URL,
    },
}


# django-axes
# https://django-axes.readthedocs.io/en/latest/4_configuration.html#configuring-caches

AXES_CACHE = 'default'
