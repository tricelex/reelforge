from __future__ import annotations

from django.http import HttpResponse
from django.urls import path

app_name = "clipping"


def _stub(request, **kwargs):  # type: ignore[no-untyped-def]
    return HttpResponse("stub")


urlpatterns = [
    # Stub URLs replaced in Task 5
    path("jobs/", _stub, name="job_list"),
    path("jobs/<uuid:pk>/", _stub, name="job_detail"),
]
