"""Conftest for test_server tests."""

import pytest
from django.conf import LazySettings


@pytest.fixture(autouse=True)
def _reset_string_if_invalid(settings: LazySettings) -> None:
    """Reset string_if_invalid to '' for admin view tests.

    pytest-django's --fail-on-template-vars sets string_if_invalid to a
    special class that calls pytest.fail() on any undefined template variable.
    Unfold's skeleton.html uses an intentionally-undefined variable inside a
    {% capture as is_fullwidth silent %} block as a default value — a pattern
    that is correct by design but incompatible with this strict check.

    Resetting string_if_invalid to '' restores Django's default behaviour,
    allowing Unfold's capture-based defaults to work without false failures.
    """
    for template in settings.TEMPLATES:
        template.setdefault('OPTIONS', {})['string_if_invalid'] = ''


@pytest.fixture(autouse=True)
def _remove_debug_toolbar_middleware(settings: LazySettings) -> None:
    """Remove debug_toolbar middleware for admin view tests.

    development.py adds DebugToolbarMiddleware to MIDDLEWARE. The toolbar's
    show callback checks a module-level DEBUG=True variable (not settings.DEBUG),
    so it fires for superusers regardless. When tests set settings.DEBUG=False,
    the djdt URL namespace is not registered, causing NoReverseMatch when the
    toolbar attempts to render. Removing the middleware from tests avoids this.
    """
    settings.MIDDLEWARE = tuple(
        m for m in settings.MIDDLEWARE if 'debug_toolbar' not in m
    )
