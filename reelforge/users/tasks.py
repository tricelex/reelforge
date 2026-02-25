from celery import shared_task

from reelforge.users.models import User


@shared_task()
def get_users_count() -> int:
    """A pointless Celery task to demonstrate usage."""
    return User.objects.count()


@shared_task()
def print_users_count() -> None:
    """A pointless Celery task to demonstrate usage."""
    User.objects.count()
    return 9999
