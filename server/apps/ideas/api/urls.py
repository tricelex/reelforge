"""URL routing for ideation DMR API."""

from dmr.routing import path

from server.apps.ideas.api import views

app_name = 'ideas_api'

urlpatterns = [
    path(
        'ideas/',
        views.IdeaCollectionController.as_view(),
        name='idea-collection',
    ),
    path(
        'ideas/<uuid:idea_id>/',
        views.IdeaDetailController.as_view(),
        name='idea-detail',
    ),
    path(
        'ideas/<uuid:idea_id>/promote/',
        views.IdeaPromoteController.as_view(),
        name='idea-promote',
    ),
    path(
        'channels/<uuid:channel_id>/ideas/generate/',
        views.ChannelIdeaGenerateController.as_view(),
        name='channel-ideas-generate',
    ),
    path(
        'niches/<uuid:niche_id>/ideas/generate/',
        views.NicheIdeaGenerateController.as_view(),
        name='niche-ideas-generate',
    ),
]
