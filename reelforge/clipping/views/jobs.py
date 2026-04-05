from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from ***REMOVED***.clipping.models import ClippingJob

_FSM_STAGE_ORDER = [
    ClippingJob.Status.INITIALIZING,
    ClippingJob.Status.DOWNLOADING,
    ClippingJob.Status.TRANSCRIBING,
    ClippingJob.Status.ANALYZING,
    ClippingJob.Status.AWAITING_CLIP_APPROVAL,
    ClippingJob.Status.RENDERING,
    ClippingJob.Status.DISTRIBUTING,
    ClippingJob.Status.COMPLETED,
]

_FSM_STAGE_LABELS = [
    (ClippingJob.Status.INITIALIZING, "Init"),
    (ClippingJob.Status.DOWNLOADING, "Download"),
    (ClippingJob.Status.TRANSCRIBING, "Transcribe"),
    (ClippingJob.Status.ANALYZING, "Analyze"),
    (ClippingJob.Status.AWAITING_CLIP_APPROVAL, "Approval"),
    (ClippingJob.Status.RENDERING, "Render"),
    (ClippingJob.Status.DISTRIBUTING, "Distribute"),
    (ClippingJob.Status.COMPLETED, "Done"),
]


def _get_completed_stages(job: ClippingJob) -> set[str]:
    """Return set of stage status values that precede the current status."""
    try:
        current_idx = _FSM_STAGE_ORDER.index(job.status)
    except ValueError:
        current_idx = 0
    return {s.value for s in _FSM_STAGE_ORDER[:current_idx]}


@staff_member_required
def job_list(request):
    status_filter = request.GET.get("status", "")
    jobs = ClippingJob.objects.select_related("channel").order_by("-created_at")

    if status_filter:
        jobs = jobs.filter(status=status_filter)

    context = {
        "jobs": jobs,
        "status_filter": status_filter,
        "status_choices": ClippingJob.Status.choices,
        "nav_section": "clipping",
    }
    return render(request, "clipping/job_list.html", context)


@staff_member_required
def job_detail(request, job_id):
    job = get_object_or_404(
        ClippingJob.objects.select_related("channel").prefetch_related(
            "candidates__layout_config",
            "candidates__style_config",
        ),
        id=job_id,
    )
    candidates = job.candidates.order_by("-relevance_score")

    context = {
        "job": job,
        "candidates": candidates,
        "nav_section": "clipping",
        "fsm_stages": _FSM_STAGE_LABELS,
        "job_completed_stages": _get_completed_stages(job),
    }
    return render(request, "clipping/job_detail.html", context)


@staff_member_required
def job_status_partial(request, job_id):
    """HTMX partial — returns just the stage tracker strip."""
    job = get_object_or_404(ClippingJob, id=job_id)
    terminal = job.status in (
        ClippingJob.Status.COMPLETED,
        ClippingJob.Status.FAILED,
    )
    return render(
        request,
        "clipping/partials/job_status.html",
        {
            "job": job,
            "fsm_stages": _FSM_STAGE_LABELS,
            "job_completed_stages": _get_completed_stages(job),
            "terminal": terminal,
        },
    )
