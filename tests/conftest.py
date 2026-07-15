"""
This module is used to provide configuration, fixtures, and plugins for pytest.

It may be also used for extending doctest's context:
1. https://docs.python.org/3/library/doctest.html
2. https://docs.pytest.org/en/latest/doctest.html
"""

import os

import pytest

# Set provider API keys before any test constructs a PydanticAI Agent.
# With @lru_cache lazy init, agents are only created on first _agent() call
# (inside test bodies), so setting these here is sufficient.
os.environ.setdefault('OPENAI_API_KEY', 'test-dummy-key')
os.environ.setdefault('PYANNOTEAI_API_KEY', 'test-dummy-key')
os.environ.setdefault('FAL_KEY', 'test-dummy-key')
os.environ.setdefault('EXA_API_KEY', 'test-dummy-key')
os.environ.setdefault('ELEVENLABS_API_KEY', 'test-dummy-key')
from django.conf import LazySettings

pytest_plugins = [
    # Should be the first custom one:
    'plugins.django_settings',
    'plugins.auth',
    # TODO: add your own plugins here!
    'plugins.main.main_templates',
    'plugins.taskiq_broker',
]


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
    show callback checks a module-level DEBUG=True variable (not settings.DEBUG)
    so it fires for superusers regardless. When tests set settings.DEBUG=False,
    the djdt URL namespace is not registered, causing NoReverseMatch when the
    toolbar attempts to render. Removing the middleware from tests avoids this.
    """
    settings.MIDDLEWARE = tuple(
        m for m in settings.MIDDLEWARE if 'debug_toolbar' not in m
    )
