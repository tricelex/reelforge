from celery import shared_task

from ***REMOVED***.users.models import User


@shared_task()
def get_users_count() -> int:
    """A pointless Celery task to demonstrate usage."""
    return User.objects.count()


@shared_task()
def print_users_count() -> None:
    """A pointless Celery task to demonstrate usage."""
    count = User.objects.count()
    print(f"There are {count} users in the database.")
