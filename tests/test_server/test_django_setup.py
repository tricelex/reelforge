"""Tests for server/common/django_setup.py."""


def test_setup_django_is_idempotent() -> None:
    from django.apps import apps

    from server.common import django_setup

    assert apps.ready
    django_setup.setup_django()
    assert apps.ready
