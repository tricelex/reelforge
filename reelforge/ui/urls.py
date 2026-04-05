from __future__ import annotations

from django.urls import path

from reelforge.ui.views import ActiveJobsPartialView
from reelforge.ui.views import DashboardView

app_name = "ui"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("partials/active-jobs/", ActiveJobsPartialView.as_view(), name="active_jobs_partial"),
]
