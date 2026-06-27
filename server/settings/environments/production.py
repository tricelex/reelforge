"""
This file contains all the settings used in production.

This file is required and if development.py is present these
values are overridden.
"""

import os

from dmr.settings import Settings

from server.settings.components import config
from server.settings.components.api import DMR_SETTINGS

# Production flags:
# https://docs.djangoproject.com/en/6.0/howto/deployment/

DEBUG = True

_railway_domain: str = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')

ALLOWED_HOSTS: list[str] = [
    config('DOMAIN_NAME'),
    'reelforge-production-9dda.up.railway.app',
    'reelforge-frontend-production.up.railway.app',
    'reelforge-production-736a.up.railway.app',
    'localhost',
    '0.0.0.0',  # noqa: S104
    '127.0.0.1',
    '[::1]',
]
if _railway_domain:
    ALLOWED_HOSTS.append(_railway_domain)

CSRF_TRUSTED_ORIGINS: list[str] = [
    f'https://{config("DOMAIN_NAME")}',
    'https://reelforge-production-736a.up.railway.app',
]
if _railway_domain:
    CSRF_TRUSTED_ORIGINS.append(f'https://{_railway_domain}')




# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

_PASS = 'django.contrib.auth.password_validation'  # noqa: S105
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': f'{_PASS}.UserAttributeSimilarityValidator'},
    {'NAME': f'{_PASS}.MinimumLengthValidator'},
    {'NAME': f'{_PASS}.CommonPasswordValidator'},
    {'NAME': f'{_PASS}.NumericPasswordValidator'},
]


# Security
# https://docs.djangoproject.com/en/6.0/topics/security/

SECURE_HSTS_SECONDS = 31536000  # the same as Caddy has
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [
    # This is required for healthcheck to work:
    '^health/',
]

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True


# django-modern-rest
# https://django-modern-rest.rtfd.io

DMR_SETTINGS[Settings.validate_responses] = False
