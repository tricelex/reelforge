"""Top-level analytics routes mounted at /api/."""

from dmr.routing import path

from server.apps.analytics.api import views

app_name = 'analytics_root'

urlpatterns = [
    path(
        'dashboard/',
        views.DashboardController.as_view(),
        name='dashboard',
    ),
]
