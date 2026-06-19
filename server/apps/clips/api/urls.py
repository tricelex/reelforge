"""URL routing for the clips API."""

from dmr.routing import path

from server.apps.clips.api import views

app_name = 'clips'

urlpatterns = [
    path(
        'runs/<uuid:run_id>/candidates/',
        views.ClipCandidateListView.as_view(),
        name='candidate_list',
    ),
    path(
        'runs/<uuid:run_id>/approve-gate/',
        views.ClipApproveGateView.as_view(),
        name='approve_gate',
    ),
    path(
        'candidates/<uuid:candidate_id>/',
        views.ClipCandidateDetailView.as_view(),
        name='candidate_detail',
    ),
    path(
        'candidates/<uuid:candidate_id>/approve/',
        views.ClipCandidateApproveView.as_view(),
        name='candidate_approve',
    ),
    path(
        'candidates/<uuid:candidate_id>/reject/',
        views.ClipCandidateRejectView.as_view(),
        name='candidate_reject',
    ),
]
