"""URL routing for channels DMR API."""

from dmr.routing import path

from server.apps.channels.api import character_views, views

app_name = 'channels_api'

channel_urlpatterns = [
    path(
        'channels/',
        views.ChannelCollectionController.as_view(),
        name='channel-collection',
    ),
    path(
        'channels/<uuid:channel_id>/',
        views.ChannelDetailController.as_view(),
        name='channel-detail',
    ),
    path(
        'channels/<uuid:channel_id>/branding/',
        views.ChannelBrandingController.as_view(),
        name='channel-branding',
    ),
    path(
        'channels/<uuid:channel_id>/assembly-style/',
        views.ChannelAssemblyStyleController.as_view(),
        name='channel-assembly-style',
    ),
    path(
        'channels/<uuid:channel_id>/graduation-status/',
        views.ChannelGraduationStatusController.as_view(),
        name='channel-graduation-status',
    ),
    path(
        'channels/<uuid:channel_id>/niche/',
        character_views.NicheConfigController.as_view(),
        name='channel-niche',
    ),
]

youtube_urlpatterns = [
    path(
        'channels/<uuid:channel_id>/youtube/connect/',
        views.YouTubeConnectController.as_view(),
        name='youtube-connect',
    ),
    path(
        'channels/<uuid:channel_id>/youtube/callback/',
        views.YouTubeCallbackController.as_view(),
        name='youtube-callback',
    ),
    path(
        'channels/<uuid:channel_id>/youtube/status/',
        views.YouTubeStatusController.as_view(),
        name='youtube-status',
    ),
]

character_urlpatterns = [
    path(
        'characters/',
        character_views.CharacterCollectionController.as_view(),
        name='character-collection',
    ),
    path(
        'characters/<uuid:character_id>/',
        character_views.CharacterDetailController.as_view(),
        name='character-detail',
    ),
    path(
        'characters/<uuid:character_id>/sessions/',
        character_views.CharacterSessionCollectionController.as_view(),
        name='character-session-collection',
    ),
    path(
        'characters/<uuid:character_id>/sessions/<uuid:session_id>/',
        character_views.CharacterSessionDetailController.as_view(),
        name='character-session-detail',
    ),
    path(
        'characters/<uuid:character_id>/sessions/<uuid:session_id>/rounds/',
        character_views.CharacterRoundController.as_view(),
        name='character-round',
    ),
    path(
        'characters/<uuid:character_id>/approve/',
        character_views.CharacterApproveController.as_view(),
        name='character-approve',
    ),
    path(
        'characters/<uuid:character_id>/promote/',
        character_views.CharacterPromoteController.as_view(),
        name='character-promote',
    ),
    path(
        'characters/<uuid:character_id>/sheet/expand/',
        character_views.CharacterSheetExpandController.as_view(),
        name='character-sheet-expand',
    ),
]

urlpatterns = [
    *channel_urlpatterns,
    *youtube_urlpatterns,
    *character_urlpatterns,
]
