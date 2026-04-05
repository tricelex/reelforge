from __future__ import annotations

import logging

from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from django_fsm import TransitionNotAllowed
from django_fsm import can_proceed

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClipLayoutConfig
from reelforge.clipping.models import ClipRenderMode
from reelforge.clipping.models import ClipRenderStyleMixin
from reelforge.clipping.models import ClipStyleConfig
from reelforge.clipping.models import ClipTimedOverlay
from reelforge.clipping.models import ClippingJob
from reelforge.clipping.tasks import preview_clip_layout
from reelforge.clipping.tasks import render_clip
from reelforge.ui.mixins import StaffRequiredMixin

_BOOLEAN_STYLE_FIELDS = frozenset({
    "caption_enabled",
    "hook_enabled",
    "watermark_enabled",
    "progress_bar_enabled",
    "music_enabled",
})

_INT_STYLE_FIELDS = frozenset({
    "caption_size",
    "caption_stroke_width",
    "watermark_size",
    "progress_bar_height",
    "hook_size",
})

_FLOAT_STYLE_FIELDS = frozenset({
    "hook_duration_sec",
    "transition_duration_sec",
    "watermark_opacity",
    "music_volume_db",
    "music_fade_in_sec",
    "music_fade_out_sec",
})

_STYLE_FIELD_SET = frozenset(ClipRenderStyleMixin.STYLE_FIELD_NAMES)

logger = logging.getLogger("reelforge.clipping")


class CandidateApproveView(StaffRequiredMixin, View):
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(
            ClipCandidate.objects.select_related("clipping_job__channel"), id=candidate_id
        )
        candidate.approved = True
        candidate.status = ClipCandidate.CandidateStatus.APPROVED
        candidate.approved_by = request.user
        candidate.approved_at = timezone.now()
        candidate.save(
            update_fields=["approved", "status", "approved_by", "approved_at", "updated_at"]
        )
        logger.info(
            "Clip candidate approved",
            extra={"candidate_id": str(candidate_id), "user": request.user.email},
        )
        return HttpResponse(
            render_to_string(
                "clipping/partials/candidate_row.html",
                {"candidate": candidate, "job": candidate.clipping_job},
                request=request,
            )
        )


class CandidateRejectView(StaffRequiredMixin, View):
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(
            ClipCandidate.objects.select_related("clipping_job__channel"), id=candidate_id
        )
        candidate.approved = False
        candidate.status = ClipCandidate.CandidateStatus.REJECTED
        candidate.save(update_fields=["approved", "status", "updated_at"])
        logger.info(
            "Clip candidate rejected",
            extra={"candidate_id": str(candidate_id), "user": request.user.email},
        )
        return HttpResponse(
            render_to_string(
                "clipping/partials/candidate_row.html",
                {"candidate": candidate, "job": candidate.clipping_job},
                request=request,
            )
        )


class CandidateUndoRejectView(StaffRequiredMixin, View):
    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(
            ClipCandidate.objects.select_related("clipping_job__channel"), id=candidate_id
        )
        candidate.approved = None
        candidate.status = ClipCandidate.CandidateStatus.PROPOSED
        candidate.save(update_fields=["approved", "status", "updated_at"])
        return HttpResponse(
            render_to_string(
                "clipping/partials/candidate_row.html",
                {"candidate": candidate, "job": candidate.clipping_job},
                request=request,
            )
        )


class JobApproveAllView(StaffRequiredMixin, View):
    """Approve all PROPOSED candidates for a job. Returns the full candidates list HTML."""

    def post(self, request: HttpRequest, job_id: str) -> HttpResponse:
        job = get_object_or_404(ClippingJob, id=job_id)
        now = timezone.now()
        proposed = list(job.candidates.filter(status=ClipCandidate.CandidateStatus.PROPOSED))
        for candidate in proposed:
            candidate.approved = True
            candidate.status = ClipCandidate.CandidateStatus.APPROVED
            candidate.approved_by = request.user
            candidate.approved_at = now
            candidate.save(
                update_fields=["approved", "status", "approved_by", "approved_at", "updated_at"]
            )
        all_candidates = job.candidates.order_by("-relevance_score")
        logger.info(
            "Approved all candidates for job",
            extra={"job_id": str(job_id), "count": len(proposed), "user": request.user.email},
        )
        html = "".join(
            render_to_string(
                "clipping/partials/candidate_row.html",
                {"candidate": c, "job": job},
                request=request,
            )
            for c in all_candidates
        )
        return HttpResponse(html)


class JobStartRenderView(StaffRequiredMixin, View):
    """Trigger render_clip task for all APPROVED candidates."""

    def post(self, request: HttpRequest, job_id: str) -> HttpResponse:
        job = get_object_or_404(ClippingJob, id=job_id)
        approved_candidates = list(
            job.candidates.filter(status=ClipCandidate.CandidateStatus.APPROVED)
        )
        triggered = 0
        for candidate in approved_candidates:
            render_clip.delay(str(candidate.id))
            candidate.status = ClipCandidate.CandidateStatus.RENDERING
            candidate.save(update_fields=["status", "updated_at"])
            triggered += 1

        if triggered > 0 and can_proceed(job.begin_rendering):
            try:
                job.begin_rendering()
                job.save(update_fields=["status", "updated_at"])
            except TransitionNotAllowed:
                logger.warning(
                    "Cannot transition job to RENDERING",
                    extra={"job_id": str(job_id), "current_status": job.status},
                )

        logger.info(
            "Started render for approved candidates",
            extra={"job_id": str(job_id), "triggered": triggered, "user": request.user.email},
        )
        response = HttpResponse(status=204)
        response["HX-Redirect"] = f"/app/clipping/{job_id}/"
        return response


class CandidateDetailView(StaffRequiredMixin, TemplateView):
    template_name = "clipping/candidate_detail.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        candidate = get_object_or_404(
            ClipCandidate.objects.select_related("clipping_job__channel").prefetch_related(
                "timed_overlays"
            ),
            pk=self.kwargs["candidate_id"],
        )
        context.update({
            "candidate": candidate,
            "job": candidate.clipping_job,
            "layout": getattr(candidate, "layout_config", None),
            "style": getattr(candidate, "style_config", None),
            "renders": candidate.renders.prefetch_related("stage_results").order_by("-created_at"),
            "timed_overlays": list(candidate.timed_overlays.all()),
            "nav_section": "clipping",
        })
        return context


class UpdateLayoutConfigView(StaffRequiredMixin, View):
    """Save render_mode and/or render_format; return the swapped layout editor partial."""

    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        layout, _ = ClipLayoutConfig.objects.get_or_create(candidate=candidate)
        update_fields: list[str] = ["updated_at"]
        if "render_mode" in request.POST:
            layout.render_mode = request.POST["render_mode"]
            update_fields.append("render_mode")
        if "render_format" in request.POST:
            layout.render_format = request.POST["render_format"]
            update_fields.append("render_format")
        layout.save(update_fields=update_fields)
        return HttpResponse(
            render_to_string(
                "clipping/partials/layout_editor.html",
                {"candidate": candidate, "layout": layout},
                request=request,
            )
        )


class UpdateLayoutRegionsView(StaffRequiredMixin, View):
    """Save drag-editor coordinate fields. Returns 200 with no body (hx-swap='none')."""

    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        layout, _ = ClipLayoutConfig.objects.get_or_create(candidate=candidate)
        coord_fields = [
            "manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h",
            "region_a_x", "region_a_y", "region_a_w", "region_a_h",
            "region_b_x", "region_b_y", "region_b_w", "region_b_h",
        ]
        update_fields: list[str] = ["updated_at"]
        for field in coord_fields:
            if field in request.POST and request.POST[field] != "":
                try:
                    setattr(layout, field, int(request.POST[field]))
                    update_fields.append(field)
                except (ValueError, TypeError):
                    pass
        if "stack_ratio" in request.POST:
            try:
                val = float(request.POST["stack_ratio"])
                if 0.3 <= val <= 0.8:
                    layout.stack_ratio = val
                    update_fields.append("stack_ratio")
            except (ValueError, TypeError):
                pass
        layout.save(update_fields=update_fields)
        return HttpResponse(status=200)


class ResetSmartCropView(StaffRequiredMixin, View):
    """Clear manual Smart Crop coordinates; return refreshed layout editor partial."""

    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        layout = get_object_or_404(ClipLayoutConfig, candidate=candidate)
        layout.manual_crop_x = None
        layout.manual_crop_y = None
        layout.manual_crop_w = None
        layout.manual_crop_h = None
        layout.save(update_fields=[
            "manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h", "updated_at",
        ])
        return HttpResponse(
            render_to_string(
                "clipping/partials/layout_editor.html",
                {"candidate": candidate, "layout": layout},
                request=request,
            )
        )


class UpdateStyleConfigView(StaffRequiredMixin, View):
    """Save any style config fields sent in POST. Called on blur/change from style panels."""

    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        style, _ = ClipStyleConfig.objects.get_or_create(candidate=candidate)
        update_fields: list[str] = ["updated_at"]
        for field_name in _STYLE_FIELD_SET - {"emoji_keyword_map"}:
            if field_name in _BOOLEAN_STYLE_FIELDS:
                val = field_name in request.POST
                setattr(style, field_name, val)
                update_fields.append(field_name)
            elif field_name in request.POST:
                raw = request.POST[field_name]
                try:
                    if field_name in _INT_STYLE_FIELDS:
                        setattr(style, field_name, int(raw))
                    elif field_name in _FLOAT_STYLE_FIELDS:
                        setattr(style, field_name, float(raw))
                    else:
                        setattr(style, field_name, raw)
                    update_fields.append(field_name)
                except (ValueError, TypeError):
                    pass
        style.save(update_fields=update_fields)
        return HttpResponse(status=200)


class TriggerPreviewView(StaffRequiredMixin, View):
    """Fire the preview_clip_layout Celery task. Returns the polling preview panel."""

    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        layout = get_object_or_404(ClipLayoutConfig, candidate=candidate)
        preview_clip_layout.delay(str(layout.pk))
        return HttpResponse(
            render_to_string(
                "clipping/partials/preview_panel.html",
                {"candidate": candidate, "layout": layout, "polling": True},
                request=request,
            )
        )


class PreviewStatusView(StaffRequiredMixin, View):
    """HTMX polling endpoint: returns preview panel partial."""

    def get(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        layout = getattr(candidate, "layout_config", None)
        is_ready = layout is not None and bool(layout.preview_image)
        return HttpResponse(
            render_to_string(
                "clipping/partials/preview_panel.html",
                {"candidate": candidate, "layout": layout, "polling": not is_ready},
                request=request,
            )
        )


class AddOverlayView(StaffRequiredMixin, View):
    """Create a new timed overlay with defaults; return the new overlay row partial."""

    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        overlay = ClipTimedOverlay.objects.create(
            candidate=candidate,
            text="New overlay",
            start_sec=0.0,
            end_sec=5.0,
        )
        return HttpResponse(
            render_to_string(
                "clipping/partials/overlay_row.html",
                {"overlay": overlay, "candidate": candidate},
                request=request,
            )
        )


class UpdateOverlayView(StaffRequiredMixin, View):
    """Save text/time fields for a timed overlay."""

    def post(self, request: HttpRequest, overlay_id: str) -> HttpResponse:
        overlay = get_object_or_404(ClipTimedOverlay, pk=overlay_id)
        update_fields: list[str] = ["updated_at"]
        if "text" in request.POST:
            overlay.text = request.POST["text"]
            update_fields.append("text")
        for field in ("start_sec", "end_sec", "position_x", "position_y", "font_size"):
            if field in request.POST:
                try:
                    val: float | int = (
                        float(request.POST[field]) if "sec" in field else int(request.POST[field])
                    )
                    setattr(overlay, field, val)
                    update_fields.append(field)
                except (ValueError, TypeError):
                    pass
        overlay.save(update_fields=update_fields)
        return HttpResponse(status=200)


class DeleteOverlayView(StaffRequiredMixin, View):
    """Delete a timed overlay; return empty 200 (HTMX outerHTML swap removes the row)."""

    def post(self, request: HttpRequest, overlay_id: str) -> HttpResponse:
        overlay = get_object_or_404(ClipTimedOverlay, pk=overlay_id)
        overlay.delete()
        return HttpResponse(status=200)


class UpdateRenderGatesView(StaffRequiredMixin, View):
    """Save the render_gates list for a candidate."""

    def post(self, request: HttpRequest, candidate_id: str) -> HttpResponse:
        candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
        raw_gates = request.POST.get("gates", "").strip()
        gates: list[int] = []
        if raw_gates:
            for part in raw_gates.split(","):
                try:
                    val = int(part.strip())
                    if 1 <= val <= 10:
                        gates.append(val)
                except (ValueError, TypeError):
                    pass
        candidate.render_gates = sorted(set(gates))
        candidate.save(update_fields=["render_gates", "updated_at"])
        return HttpResponse(
            render_to_string(
                "clipping/partials/gates_panel.html",
                {"candidate": candidate},
                request=request,
            )
        )


# Keep module-level references so existing imports still resolve during transition
__all__ = [
    "CandidateApproveView",
    "CandidateRejectView",
    "CandidateUndoRejectView",
    "JobApproveAllView",
    "JobStartRenderView",
    "CandidateDetailView",
    "UpdateLayoutConfigView",
    "UpdateLayoutRegionsView",
    "ResetSmartCropView",
    "UpdateStyleConfigView",
    "TriggerPreviewView",
    "PreviewStatusView",
    "AddOverlayView",
    "UpdateOverlayView",
    "DeleteOverlayView",
    "UpdateRenderGatesView",
]
