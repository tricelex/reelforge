from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.utils import timezone

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClippingJob


@staff_member_required
def dashboard(request):
    active_jobs = (
        ClippingJob.objects.filter(
            status__in=[
                ClippingJob.Status.INITIALIZING,
                ClippingJob.Status.DOWNLOADING,
                ClippingJob.Status.TRANSCRIBING,
                ClippingJob.Status.ANALYZING,
                ClippingJob.Status.AWAITING_CLIP_APPROVAL,
                ClippingJob.Status.RENDERING,
                ClippingJob.Status.DISTRIBUTING,
            ]
        )
        .select_related("channel")
        .order_by("-created_at")[:20]
    )

    awaiting_approval = (
        ClippingJob.objects.filter(
            status=ClippingJob.Status.AWAITING_CLIP_APPROVAL,
        )
        .select_related("channel")
        .order_by("-updated_at")
    )

    completed_today_count = ClippingJob.objects.filter(
        status=ClippingJob.Status.COMPLETED,
        completed_at__date=timezone.now().date(),
    ).count()

    context = {
        "active_jobs": active_jobs,
        "awaiting_approval": awaiting_approval,
        "active_jobs_count": active_jobs.count(),
        "awaiting_approval_count": awaiting_approval.count(),
        "completed_today_count": completed_today_count,
        "nav_section": "dashboard",
    }
    return render(request, "ui/dashboard.html", context)
