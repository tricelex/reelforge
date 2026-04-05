from __future__ import annotations

from django.urls import path

from reelforge.ui import views

app_name = "ui"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("partials/active-jobs/", views.active_jobs_partial, name="active_jobs_partial"),
]
