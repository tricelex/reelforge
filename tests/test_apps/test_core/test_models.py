"""Tests for core models."""

import pytest
from django.contrib.auth.models import User

from server.apps.core.logic.constants import UserRole
from server.apps.core.models import UserProfile


@pytest.mark.django_db
def test_user_profile_str() -> None:
    """UserProfile string includes username and role."""
    user = User.objects.create_user(username='alice', password='pass')
    profile = UserProfile.objects.create(user=user, role=UserRole.REVIEWER)
    assert str(profile) == 'alice (reviewer)'
