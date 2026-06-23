"""Core platform models."""

from typing import ClassVar, override

from django.conf import settings
from django.db import models

from server.apps.core.logic.constants import UserRole
from server.common.models import TimeStampedModel


class UserProfile(TimeStampedModel):
    """Extended profile for Django auth users (role-based API access)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
    )
    role = models.CharField(
        max_length=10,
        choices=UserRole.choices,
        default=UserRole.OPERATOR,
    )

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                name='core_userprofile_role_valid',
                condition=models.Q(role__in=UserRole.values),
            ),
        ]

    @override
    def __str__(self) -> str:
        return f'{self.user.username} ({self.role})'
