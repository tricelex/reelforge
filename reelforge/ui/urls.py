from __future__ import annotations

from django.urls import include
from django.urls import path

from reelforge.ui import views

app_name = "ui"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("clipping/", include("reelforge.clipping.urls", namespace="clipping")),
]
