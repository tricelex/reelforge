from os import environ

from server.settings.components import config

DJANGO_ENV: str = environ.get('DJANGO_ENV', 'development')

SENTRY_DSN: str = config('SENTRY_DSN', default='')
SENTRY_TRACES_SAMPLE_RATE: float = config(
    'SENTRY_TRACES_SAMPLE_RATE',
    cast=float,
    default=1.0,
)
SENTRY_PROFILES_SAMPLE_RATE: float = config(
    'SENTRY_PROFILES_SAMPLE_RATE',
    cast=float,
    default=0.1,
)

LOGFIRE_TOKEN: str = config('LOGFIRE_TOKEN', default='')
LOGFIRE_SERVICE_NAME: str = config('LOGFIRE_SERVICE_NAME', default='***REMOVED***')
