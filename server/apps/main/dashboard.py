"""Admin dashboard callback for the ReelForge admin site."""

from typing import Any

from django.contrib.auth.models import User
from django.http import HttpRequest

from server.apps.main.models import BlogPost


def dashboard_callback(
    request: HttpRequest, context: dict[str, Any],
) -> dict[str, Any]:
    """Inject KPI data into the admin dashboard context."""
    context['total_posts'] = BlogPost.objects.count()
    context['recent_posts'] = list(
        BlogPost.objects.order_by('-created_at').values(
            'id', 'title', 'created_at',
        )[:5],
    )
    context['total_users'] = User.objects.count()
    return context
