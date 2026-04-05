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
from reelforge.clipping.models import ClippingJob
from reelforge.clipping.models import ClipTimedOverlay
from reelforge.clipping.tasks import render_clip

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
