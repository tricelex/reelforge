"""URL routing for analytics DMR API."""

from dmr.routing import path

from server.apps.analytics.api import views

app_name = 'analytics_api'

urlpatterns = [
    path(
        'summary/',
        views.AnalyticsSummaryController.as_view(),
        name='analytics-summary',
    ),
    path(
        'runs/<uuid:run_id>/cost/',
        views.RunCostController.as_view(),
        name='run-cost',
    ),
    path(
        'channels/<uuid:channel_id>/roi/',
        views.ChannelRoiController.as_view(),
        name='channel-roi',
    ),
    path(
        'channels/<uuid:channel_id>/stages/',
        views.ChannelStagesController.as_view(),
        name='channel-stages',
    ),
]
