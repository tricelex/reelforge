"""URL routing for the pipelines app (SSE only — DMR APIs live under api/)."""

from django.urls import path

from server.apps.pipelines.views import pipeline_events

app_name = 'pipelines'

urlpatterns = [
    path(
        'runs/<str:run_id>/events/',
        pipeline_events,
        name='run-events',
    ),
]
