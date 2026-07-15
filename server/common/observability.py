"""Sentry and Logfire initialisation helpers."""

import logging
from collections.abc import Callable
from typing import final

import logfire
import sentry_sdk
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from opentelemetry.instrumentation.utils import suppress_instrumentation
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.redis import RedisIntegration

_HEALTH_CHECK_PATH = '/health/'
_ERROR_MESSAGE_PATH = ('attributes', 'error', 'message')
_FALSE_POSITIVE_MATCHES = frozenset({'cookie', 'apikey', 'auth'})


def _normalised_scrub_match(matched: str) -> str:
    return matched.casefold().replace('_', '').replace('-', '').replace(' ', '')


def scrubbing_callback(m: logfire.ScrubMatch) -> object | None:
    """Keep benign error messages that mention cookie/api-key wording."""
    if m.path != _ERROR_MESSAGE_PATH:
        return None
    if _normalised_scrub_match(m.pattern_match.group(0)) in _FALSE_POSITIVE_MATCHES:
        return m.value
    return None


def init_sentry() -> None:
    """Initialise Sentry SDK. No-op when SENTRY_DSN is not configured."""
    if not settings.SENTRY_DSN:
        return
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.DJANGO_ENV,
        server_name=settings.LOGFIRE_SERVICE_NAME,
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
        scrubbing=logfire.ScrubbingOptions(callback=scrubbing_callback),
    )
    logfire.instrument_django(
        capture_headers=False,
        excluded_urls=_HEALTH_CHECK_PATH,
    )
    logfire.instrument_httpx()
    logfire.instrument_pydantic_ai()
    logfire.instrument_requests()
    root_logger = logging.getLogger()
    already_added = any(
        isinstance(h, logfire.LogfireLoggingHandler)
        for h in root_logger.handlers
    )
    if not already_added:
        root_logger.addHandler(logfire.LogfireLoggingHandler())


@final
class SuppressHealthCheckObservabilityMiddleware:
    """Keeps recurring health-check pings out of Logfire traces.

    `excluded_urls` on `logfire.instrument_django()` stops the top-level
    `GET /health/` request span, but the health check's own DB/cache/storage
    queries are instrumented independently (psycopg2, redis, ...) and don't
    know the request was excluded — they'd otherwise show up as orphan
    "SELECT 1" traces every time the Docker healthcheck polls. Wrapping the
    whole request in `suppress_instrumentation()` stops those too.
    """

    def __init__(
        self,
        get_response: Callable[[HttpRequest], HttpResponse],
    ) -> None:
        """Django's API-compatible constructor."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Suppress OTel/Logfire instrumentation for health check requests."""
        if request.path == _HEALTH_CHECK_PATH:
            with suppress_instrumentation():
                return self.get_response(request)
        return self.get_response(request)
