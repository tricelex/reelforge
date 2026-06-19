"""URL routing for pipeline DMR API."""

from dmr.routing import path

from server.apps.pipelines.api import views

app_name = 'pipelines_api'

urlpatterns = [
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
        'runs/<uuid:run_id>/gates/<str:gate_key>/approve/',
        views.RunGateApproveController.as_view(),
        name='gate-approve',
    ),
    path(
        'runs/<uuid:run_id>/stages/<str:stage_key>/rerun/',
        views.RunStageRerunController.as_view(),
        name='stage-rerun',
    ),
]
