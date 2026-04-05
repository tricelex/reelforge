from __future__ import annotations

import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_fsm import TransitionNotAllowed
from django_fsm import can_proceed

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClipLayoutConfig
from reelforge.clipping.models import ClipRenderMode
from reelforge.clipping.models import ClipRenderStyleMixin
from reelforge.clipping.models import ClippingJob
from reelforge.clipping.models import ClipStyleConfig
from reelforge.clipping.models import ClipTimedOverlay
from reelforge.clipping.tasks import render_clip

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


@staff_member_required
@require_POST
def candidate_approve(request: HttpRequest, candidate_id: str) -> HttpResponse:
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
    return render(
        request,
        "clipping/partials/candidate_row.html",
        {"candidate": candidate, "job": candidate.clipping_job},
    )


@staff_member_required
@require_POST
def candidate_reject(request: HttpRequest, candidate_id: str) -> HttpResponse:
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
    return render(
        request,
        "clipping/partials/candidate_row.html",
        {"candidate": candidate, "job": candidate.clipping_job},
    )


@staff_member_required
@require_POST
def candidate_undo_reject(request: HttpRequest, candidate_id: str) -> HttpResponse:
    candidate = get_object_or_404(
        ClipCandidate.objects.select_related("clipping_job__channel"), id=candidate_id
    )
    candidate.approved = None
    candidate.status = ClipCandidate.CandidateStatus.PROPOSED
    candidate.save(update_fields=["approved", "status", "updated_at"])
    return render(
        request,
        "clipping/partials/candidate_row.html",
        {"candidate": candidate, "job": candidate.clipping_job},
    )


@staff_member_required
@require_POST
def job_approve_all(request: HttpRequest, job_id: str) -> HttpResponse:
    """Approve all PROPOSED candidates for a job. Returns the full candidates list HTML."""
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


@staff_member_required
@require_POST
def job_start_render(request: HttpRequest, job_id: str) -> HttpResponse:
    """Trigger render_clip task for all APPROVED candidates."""
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


@staff_member_required
def candidate_detail(request: HttpRequest, candidate_id: str) -> HttpResponse:
    candidate = get_object_or_404(
        ClipCandidate.objects.select_related(
            "clipping_job__channel",
        ).prefetch_related("timed_overlays"),
        pk=candidate_id,
    )
    layout = getattr(candidate, "layout_config", None)
    style = getattr(candidate, "style_config", None)
    renders = candidate.renders.prefetch_related("stage_results").order_by("-created_at")

    return render(
        request,
        "clipping/candidate_detail.html",
        {
            "candidate": candidate,
            "job": candidate.clipping_job,
            "layout": layout,
            "style": style,
            "renders": renders,
            "timed_overlays": list(candidate.timed_overlays.all()),
            "nav_section": "clipping",
        },
    )


@staff_member_required
@require_POST
def update_layout_config(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """Save render_mode and/or render_format; return the swapped layout editor partial."""
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

    return render(
        request,
        "clipping/partials/layout_editor.html",
        {"candidate": candidate, "layout": layout},
    )


@staff_member_required
@require_POST
def update_layout_regions(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """Save drag-editor coordinate fields. Returns 200 with no body (hx-swap='none')."""
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


@staff_member_required
@require_POST
def reset_smart_crop(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """Clear manual Smart Crop coordinates; return refreshed layout editor partial."""
    candidate = get_object_or_404(ClipCandidate, pk=candidate_id)
    layout = get_object_or_404(ClipLayoutConfig, candidate=candidate)
    layout.manual_crop_x = None
    layout.manual_crop_y = None
    layout.manual_crop_w = None
    layout.manual_crop_h = None
    layout.save(update_fields=[
        "manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h", "updated_at",
    ])
    return render(
        request,
        "clipping/partials/layout_editor.html",
        {"candidate": candidate, "layout": layout},
    )


@staff_member_required
@require_POST
def update_style_config(request: HttpRequest, candidate_id: str) -> HttpResponse:
    """Save any style config fields sent in POST. Called on blur/change from style panels."""
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
