"""URL routing for the pipelines app."""

from django.urls import path

from server.apps.pipelines.views import gate_approve, pipeline_events

app_name = 'pipelines'

urlpatterns = [
    path(
        'runs/<str:run_id>/events/',
        pipeline_events,
        name='run-events',
    ),
    path(
        'runs/<str:run_id>/gates/<str:gate_key>/approve/',
        gate_approve,
        name='gate-approve',
    ),
]
