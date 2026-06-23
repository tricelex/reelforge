"""Public enum registry endpoint."""

from dmr.routing import path

from server.apps.core.api import views

app_name = 'core_enums'

urlpatterns = [
    path('', views.EnumsController.as_view(), name='enums'),
]
