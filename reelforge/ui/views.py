from __future__ import annotations

from django.db.models import Count
from django.utils import timezone
from django.views.generic import TemplateView

from ***REMOVED***.clipping.models import ClippingJob
from ***REMOVED***.ui.mixins import StaffRequiredMixin

_ACTIVE_STATUSES = [
    ClippingJob.Status.INITIALIZING,
    ClippingJob.Status.DOWNLOADING,
    ClippingJob.Status.TRANSCRIBING,
    ClippingJob.Status.ANALYZING,
    ClippingJob.Status.AWAITING_CLIP_APPROVAL,
    ClippingJob.Status.RENDERING,
    ClippingJob.Status.DISTRIBUTING,
]


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = "ui/dashboard.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        active_jobs = (
            ClippingJob.objects.filter(status__in=_ACTIVE_STATUSES)
            .select_related("social_account")
            .order_by("-created_at")[:20]
        )
        awaiting_approval = (
            ClippingJob.objects.filter(status=ClippingJob.Status.AWAITING_CLIP_APPROVAL)
            .select_related("social_account")
            .annotate(candidate_count=Count("candidates"))
            .order_by("-updated_at")
        )
        context.update({
            "active_jobs": active_jobs,
            "awaiting_approval": awaiting_approval,
            "active_jobs_count": active_jobs.count(),
            "awaiting_approval_count": awaiting_approval.count(),
            "completed_today_count": ClippingJob.objects.filter(
                status=ClippingJob.Status.COMPLETED,
                completed_at__date=today,
            ).count(),
            "nav_active": "dashboard",
        })
        return context


class ActiveJobsPartialView(StaffRequiredMixin, TemplateView):
    """HTMX partial — polled every 2s to refresh the active jobs table."""

    template_name = "ui/partials/active_jobs.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["active_jobs"] = (
            ClippingJob.objects.filter(status__in=_ACTIVE_STATUSES)
            .select_related("social_account")
            .order_by("-created_at")[:20]
        )
        return context
