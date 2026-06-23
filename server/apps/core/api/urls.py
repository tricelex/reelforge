"""URL routing for the core API."""

from dmr.routing import path

from server.apps.core.api import views

app_name = 'core'

urlpatterns = [
    path('login/', views.LoginController.as_view(), name='login'),
    path('refresh/', views.RefreshController.as_view(), name='refresh'),
    path('me/', views.MeController.as_view(), name='me'),
]
