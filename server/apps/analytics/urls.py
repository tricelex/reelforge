"""URL routing for the analytics app."""

from django.urls import path

from server.apps.analytics import views

app_name = 'analytics'

urlpatterns = [
    path('runs/<str:run_id>/cost/', views.run_cost_view, name='run-cost'),
    path(
        'channels/<str:channel_id>/roi/',
        views.channel_roi_view,
        name='channel-roi',
    ),
    path(
        'channels/<str:channel_id>/stages/',
        views.channel_stages_view,
        name='channel-stages',
    ),
]
