from __future__ import annotations

from django.urls import path

from ***REMOVED***.clipping.views.candidates import AddOverlayView
from ***REMOVED***.clipping.views.candidates import CandidateApproveView
from ***REMOVED***.clipping.views.candidates import CandidateDetailView
from ***REMOVED***.clipping.views.candidates import CandidateRejectView
from ***REMOVED***.clipping.views.candidates import CandidateUndoRejectView
from ***REMOVED***.clipping.views.candidates import DeleteOverlayView
from ***REMOVED***.clipping.views.candidates import JobApproveAllView
from ***REMOVED***.clipping.views.candidates import JobStartRenderView
from ***REMOVED***.clipping.views.candidates import PreviewStatusView
from ***REMOVED***.clipping.views.candidates import ResetSmartCropView
from ***REMOVED***.clipping.views.candidates import TriggerPreviewView
from ***REMOVED***.clipping.views.candidates import UpdateLayoutConfigView
from ***REMOVED***.clipping.views.candidates import UpdateLayoutRegionsView
from ***REMOVED***.clipping.views.candidates import UpdateOverlayView
from ***REMOVED***.clipping.views.candidates import UpdateRenderGatesView
from ***REMOVED***.clipping.views.candidates import UpdateStyleConfigView
from ***REMOVED***.clipping.views.jobs import JobDetailView
from ***REMOVED***.clipping.views.jobs import JobListView
from ***REMOVED***.clipping.views.jobs import JobStatusPartialView

# Render views — currently FBVs; Task 9 will convert these to CBVs
from ***REMOVED***.clipping.views import renders as views_renders

app_name = "clipping"

urlpatterns = [
    # Job views
    path("", JobListView.as_view(), name="job_list"),
    path("<uuid:job_id>/", JobDetailView.as_view(), name="job_detail"),
    path("<uuid:job_id>/status/", JobStatusPartialView.as_view(), name="job_status_partial"),
    path("<uuid:job_id>/approve-all/", JobApproveAllView.as_view(), name="job_approve_all"),
    path("<uuid:job_id>/start-render/", JobStartRenderView.as_view(), name="job_start_render"),
    # Candidate detail + actions
    path("clips/<uuid:candidate_id>/", CandidateDetailView.as_view(), name="candidate_detail"),
    path("clips/<uuid:candidate_id>/layout/", UpdateLayoutConfigView.as_view(), name="update_layout_config"),
    path("clips/<uuid:candidate_id>/layout/regions/", UpdateLayoutRegionsView.as_view(), name="update_layout_regions"),
    path("clips/<uuid:candidate_id>/layout/reset-crop/", ResetSmartCropView.as_view(), name="reset_smart_crop"),
    path("clips/<uuid:candidate_id>/style/", UpdateStyleConfigView.as_view(), name="update_style_config"),
    path("clips/<uuid:candidate_id>/preview/trigger/", TriggerPreviewView.as_view(), name="trigger_preview"),
    path("clips/<uuid:candidate_id>/preview/status/", PreviewStatusView.as_view(), name="preview_status"),
    path("clips/<uuid:candidate_id>/overlays/add/", AddOverlayView.as_view(), name="add_overlay"),
    path("overlays/<uuid:overlay_id>/update/", UpdateOverlayView.as_view(), name="update_overlay"),
    path("overlays/<uuid:overlay_id>/delete/", DeleteOverlayView.as_view(), name="delete_overlay"),
    path("clips/<uuid:candidate_id>/approve/", CandidateApproveView.as_view(), name="candidate_approve"),
    path("clips/<uuid:candidate_id>/reject/", CandidateRejectView.as_view(), name="candidate_reject"),
    path("clips/<uuid:candidate_id>/undo-reject/", CandidateUndoRejectView.as_view(), name="candidate_undo_reject"),
    path("clips/<uuid:candidate_id>/gates/", UpdateRenderGatesView.as_view(), name="update_render_gates"),
    # Render views — Task 9 will replace these FBV references with CBVs
    path("renders/<uuid:render_id>/", views_renders.render_detail, name="render_detail"),
    path("renders/<uuid:render_id>/stages/", views_renders.stage_list_partial, name="stage_list_partial"),
    path("renders/<uuid:render_id>/rerun/<int:stage_order>/", views_renders.rerun_from_stage, name="rerun_from_stage"),
    path("renders/<uuid:render_id>/resume/", views_renders.resume_render, name="resume_render"),
]
