"""URL routing for pipeline DMR API."""

from dmr.routing import path

from server.apps.pipelines.api import (
    cast_views,
    events_views,
    review_views,
    views,
)

app_name = 'pipelines_api'

run_urlpatterns = [
    path(
        'gates/',
        views.GateCatalogController.as_view(),
        name='gate-catalog',
    ),
    path(
        'runs/',
        views.RunCollectionController.as_view(),
        name='run-collection',
    ),
    path(
        'runs/<uuid:run_id>/',
        views.RunDetailController.as_view(),
        name='run-detail',
    ),
    path(
        'runs/<uuid:run_id>/cancel/',
        views.RunCancelController.as_view(),
        name='run-cancel',
    ),
    path(
        'runs/<uuid:run_id>/pause/',
        views.RunPauseController.as_view(),
        name='run-pause',
    ),
    path(
        'runs/<uuid:run_id>/resume/',
        views.RunResumeController.as_view(),
        name='run-resume',
    ),
    path(
        'runs/<uuid:run_id>/events/token/',
        views.RunEventsTokenController.as_view(),
        name='run-events-token',
    ),
    path(
        'runs/<uuid:run_id>/events/',
        events_views.RunEventsController.as_view(),
        name='run-events',
    ),
    path(
        'runs/<uuid:run_id>/gates/<str:gate_key>/approve/',
        views.RunGateApproveController.as_view(),
        name='gate-approve',
    ),
    path(
        'runs/<uuid:run_id>/stages/<str:stage_key>/rerun/',
        views.RunStageRerunController.as_view(),
        name='stage-rerun',
    ),
    path(
        'runs/<uuid:run_id>/stages/<str:stage_key>/output/',
        views.RunStageOutputController.as_view(),
        name='run-stage-output',
    ),
    path(
        'runs/<uuid:run_id>/transcript/',
        views.RunTranscriptController.as_view(),
        name='run-transcript',
    ),
    path(
        'runs/<uuid:run_id>/assets/',
        views.RunAssetsController.as_view(),
        name='run-assets',
    ),
    path(
        'gates/waiting/',
        views.GatesWaitingController.as_view(),
        name='gates-waiting',
    ),
]

cast_urlpatterns = [
    path(
        'runs/<uuid:run_id>/cast/',
        cast_views.RunCastCollectionController.as_view(),
        name='run-cast-collection',
    ),
    path(
        'runs/<uuid:run_id>/cast/<uuid:cast_id>/',
        cast_views.RunCastDetailController.as_view(),
        name='run-cast-detail',
    ),
    path(
        'runs/<uuid:run_id>/cast/<uuid:cast_id>/sessions/',
        cast_views.RunCastSessionController.as_view(),
        name='run-cast-session',
    ),
    path(
        'runs/<uuid:run_id>/cast/<uuid:cast_id>/sessions/<uuid:session_id>/',
        cast_views.RunCastSessionDetailController.as_view(),
        name='run-cast-session-detail',
    ),
    path(
        'runs/<uuid:run_id>/cast/<uuid:cast_id>/sessions/<uuid:session_id>/rounds/',
        cast_views.RunCastRoundController.as_view(),
        name='run-cast-round',
    ),
    path(
        'runs/<uuid:run_id>/cast/<uuid:cast_id>/approve/',
        cast_views.RunCastApproveController.as_view(),
        name='run-cast-approve',
    ),
]

review_urlpatterns = [
    path(
        'runs/<uuid:run_id>/storyboard/',
        review_views.RunStoryboardController.as_view(),
        name='run-storyboard',
    ),
    path(
        'runs/<uuid:run_id>/scene-breakdown/',
        review_views.RunSceneBreakdownController.as_view(),
        name='run-scene-breakdown',
    ),
    path(
        'runs/<uuid:run_id>/scenes/<int:scene_idx>/',
        review_views.RunSceneDetailController.as_view(),
        name='run-scene-detail',
    ),
    path(
        'runs/<uuid:run_id>/preview/',
        review_views.RunPreviewController.as_view(),
        name='run-preview',
    ),
    path(
        'runs/<uuid:run_id>/publish-metadata/',
        review_views.RunPublishMetadataController.as_view(),
        name='run-publish-metadata',
    ),
    path(
        'runs/<uuid:run_id>/publish/',
        review_views.RunPublishController.as_view(),
        name='run-publish',
    ),
]

blueprint_urlpatterns = [
    path(
        'blueprints/',
        views.BlueprintCollectionController.as_view(),
        name='blueprint-collection',
    ),
]

urlpatterns = [
    *run_urlpatterns,
    *cast_urlpatterns,
    *review_urlpatterns,
    *blueprint_urlpatterns,
]
