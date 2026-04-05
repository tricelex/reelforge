from __future__ import annotations

from django.urls import include
from django.urls import path

from ***REMOVED***.ui import views

app_name = "ui"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("clipping/", include("***REMOVED***.clipping.urls", namespace="clipping")),
]
