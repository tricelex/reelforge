from __future__ import annotations

from django.urls import path

from reelforge.clipping.views import jobs

app_name = "clipping"

urlpatterns = [
    path("", jobs.job_list, name="job_list"),
    path("<uuid:job_id>/", jobs.job_detail, name="job_detail"),
    path("<uuid:job_id>/status/", jobs.job_status_partial, name="job_status_partial"),
]
