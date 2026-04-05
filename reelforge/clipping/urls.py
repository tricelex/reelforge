from __future__ import annotations

from django.urls import path

from ***REMOVED***.clipping.views import candidates
from ***REMOVED***.clipping.views import jobs
from ***REMOVED***.clipping.views import renders as views_renders

app_name = "clipping"

urlpatterns = [
    # Job views
    path("", jobs.job_list, name="job_list"),
    path("<uuid:job_id>/", jobs.job_detail, name="job_detail"),
    path("<uuid:job_id>/status/", jobs.job_status_partial, name="job_status_partial"),
    path("<uuid:job_id>/approve-all/", candidates.job_approve_all, name="job_approve_all"),
    path("<uuid:job_id>/start-render/", candidates.job_start_render, name="job_start_render"),
    # Candidate detail + actions
    path("clips/<uuid:candidate_id>/", candidates.candidate_detail, name="candidate_detail"),
    path("clips/<uuid:candidate_id>/layout/", candidates.update_layout_config, name="update_layout_config"),
    path("clips/<uuid:candidate_id>/layout/regions/", candidates.update_layout_regions, name="update_layout_regions"),
    path("clips/<uuid:candidate_id>/layout/reset-crop/", candidates.reset_smart_crop, name="reset_smart_crop"),
    path("clips/<uuid:candidate_id>/style/", candidates.update_style_config, name="update_style_config"),
    path("clips/<uuid:candidate_id>/preview/trigger/", candidates.trigger_preview, name="trigger_preview"),
    path("clips/<uuid:candidate_id>/preview/status/", candidates.preview_status, name="preview_status"),
    path("clips/<uuid:candidate_id>/overlays/add/", candidates.add_overlay, name="add_overlay"),
    path("overlays/<uuid:overlay_id>/update/", candidates.update_overlay, name="update_overlay"),
    path("overlays/<uuid:overlay_id>/delete/", candidates.delete_overlay, name="delete_overlay"),
    path("clips/<uuid:candidate_id>/approve/", candidates.candidate_approve, name="candidate_approve"),
    path("clips/<uuid:candidate_id>/reject/", candidates.candidate_reject, name="candidate_reject"),
    path("clips/<uuid:candidate_id>/undo-reject/", candidates.candidate_undo_reject, name="candidate_undo_reject"),
    path("clips/<uuid:candidate_id>/gates/", candidates.update_render_gates, name="update_render_gates"),
    # Render views
    path("renders/<uuid:render_id>/", views_renders.render_detail, name="render_detail"),
    path("renders/<uuid:render_id>/stages/", views_renders.stage_list_partial, name="stage_list_partial"),
    path("renders/<uuid:render_id>/rerun/<int:stage_order>/", views_renders.rerun_from_stage, name="rerun_from_stage"),
    path("renders/<uuid:render_id>/resume/", views_renders.resume_render, name="resume_render"),
]
