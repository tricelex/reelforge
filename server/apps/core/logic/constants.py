from django.db import models


class UserRole(models.TextChoices):
    """Team account role for API authorization."""

    OPERATOR = 'operator', 'Operator'
    REVIEWER = 'reviewer', 'Reviewer'
