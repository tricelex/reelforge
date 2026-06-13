"""Sentry and Logfire initialisation helpers."""

import logging

import logfire
import sentry_sdk
from django.conf import settings
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.redis import RedisIntegration


def init_sentry() -> None:
    """Initialise Sentry SDK. No-op when SENTRY_DSN is not configured."""
    if not settings.SENTRY_DSN:
        return
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.DJANGO_ENV,
        integrations=[
            DjangoIntegration(transaction_style='url'),
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
            ),
            RedisIntegration(),
        ],
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
        send_default_pii=False,
    )


def init_logfire() -> None:
    """Initialise Logfire. No-op when LOGFIRE_TOKEN is not configured."""
    if not settings.LOGFIRE_TOKEN:
        return
    logfire.configure(
        token=settings.LOGFIRE_TOKEN,
        service_name=settings.LOGFIRE_SERVICE_NAME,
    )
    logfire.instrument_django(capture_headers=True)
    logfire.instrument_psycopg('psycopg2')
    logfire.instrument_redis()
    logfire.instrument_httpx()
