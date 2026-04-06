from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView

from reelforge.clipping.models import ClippingJob
from reelforge.ui.mixins import StaffRequiredMixin

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


class JobListView(StaffRequiredMixin, TemplateView):
    template_name = "clipping/job_list.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        status_filter = self.request.GET.get("status", "")
        jobs = ClippingJob.objects.select_related("social_account").order_by("-created_at")
        if status_filter:
            jobs = jobs.filter(status=status_filter)
        context.update({
            "jobs": jobs,
            "status_filter": status_filter,
            "status_choices": ClippingJob.Status.choices,
            "nav_active": "clipping",
        })
        return context


class JobDetailView(StaffRequiredMixin, TemplateView):
    template_name = "clipping/job_detail.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        job = get_object_or_404(
            ClippingJob.objects.select_related("social_account").prefetch_related(
                "candidates__layout_config",
                "candidates__style_config",
            ),
            id=self.kwargs["job_id"],
        )
        context.update({
            "job": job,
            "candidates": job.candidates.order_by("-relevance_score"),
            "nav_active": "clipping",
            "fsm_stages": _FSM_STAGE_LABELS,
            "job_completed_stages": _get_completed_stages(job),
        })
        return context


class JobStatusPartialView(StaffRequiredMixin, TemplateView):
    """HTMX partial — returns just the stage tracker strip."""

    template_name = "clipping/partials/job_status.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        job = get_object_or_404(ClippingJob, id=self.kwargs["job_id"])
        context.update({
            "job": job,
            "fsm_stages": _FSM_STAGE_LABELS,
            "job_completed_stages": _get_completed_stages(job),
            "terminal": job.status in (ClippingJob.Status.COMPLETED, ClippingJob.Status.FAILED),
        })
        return context
