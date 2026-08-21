"""URL routing for channel research DMR API."""

from dmr.routing import path

from server.apps.channel_research.api import views

app_name = 'channel_research_api'

urlpatterns = [
    path(
        'channel-research/',
        views.ChannelResearchCollectionController.as_view(),
        name='job-collection',
    ),
    path(
        'channel-research/validate-spec/',
        views.ChannelResearchValidateSpecController.as_view(),
        name='validate-spec',
    ),
    path(
        'channel-research/import/',
        views.ChannelResearchImportController.as_view(),
        name='import-spec',
    ),
    path(
        'channel-research/<uuid:job_id>/',
        views.ChannelResearchDetailController.as_view(),
        name='job-detail',
    ),
    path(
        'channel-research/<uuid:job_id>/retry/',
        views.ChannelResearchRetryController.as_view(),
        name='job-retry',
    ),
]
