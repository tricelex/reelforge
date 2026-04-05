from __future__ import annotations

import logging

from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import TemplateView

from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.tasks import render_clip
from ***REMOVED***.ui.mixins import StaffRequiredMixin

logger = logging.getLogger("***REMOVED***.clipping.views")

_TERMINAL_RENDER_STATUSES = frozenset({
    ClipRender.RenderStatus.COMPLETED,
    ClipRender.RenderStatus.FAILED,
    ClipRender.RenderStatus.PAUSED_AT_GATE,
})


class RenderDetailView(StaffRequiredMixin, TemplateView):
    template_name = "clipping/render_detail.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        clip_render = get_object_or_404(
            ClipRender.objects.select_related(
                "candidate__clipping_job__channel",
                "candidate__layout_config",
            ).prefetch_related("stage_results"),
            pk=self.kwargs["render_id"],
        )
        candidate = clip_render.candidate
        context.update({
            "render": clip_render,
            "candidate": candidate,
            "layout": getattr(candidate, "layout_config", None),
            "stages": list(clip_render.stage_results.order_by("stage_order")),
            "is_terminal": clip_render.status in _TERMINAL_RENDER_STATUSES,
            "nav_active": "clipping",
        })
        return context


class StageListPartialView(StaffRequiredMixin, TemplateView):
    """HTMX polling target: refreshes the stage list. Self-stopping when render is terminal."""

    template_name = "clipping/partials/stage_list.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        clip_render = get_object_or_404(
            ClipRender.objects.prefetch_related("stage_results"),
            pk=self.kwargs["render_id"],
        )
        context.update({
            "render": clip_render,
            "stages": list(clip_render.stage_results.order_by("stage_order")),
            "is_terminal": clip_render.status in _TERMINAL_RENDER_STATUSES,
        })
        return context


class RerunFromStageView(StaffRequiredMixin, View):
    """Re-run the render pipeline from the given stage order."""

    def post(self, request: HttpRequest, render_id: str, stage_order: int) -> HttpResponse:
        clip_render = get_object_or_404(ClipRender, pk=render_id)
        clip_render.status = ClipRender.RenderStatus.RUNNING
        clip_render.paused_at_stage = None
        clip_render.last_error = ""
        clip_render.save(update_fields=["status", "paused_at_stage", "last_error", "updated_at"])
        render_clip.delay(
            str(clip_render.candidate_id),
            clip_render_id=str(clip_render.pk),
            start_from_stage=stage_order,
        )
        response = HttpResponse(status=204)
        response["HX-Redirect"] = f"/app/clipping/renders/{render_id}/"
        return response


class ResumeRenderView(StaffRequiredMixin, View):
    """Continue the pipeline from the stage after the current gate pause."""

    def post(self, request: HttpRequest, render_id: str) -> HttpResponse:
        clip_render = get_object_or_404(ClipRender, pk=render_id)
        if (
            clip_render.status != ClipRender.RenderStatus.PAUSED_AT_GATE
            or clip_render.paused_at_stage is None
        ):
            return HttpResponse("Render is not paused at a gate", status=400)
        next_stage = clip_render.paused_at_stage + 1
        clip_render.status = ClipRender.RenderStatus.RUNNING
        clip_render.paused_at_stage = None
        clip_render.save(update_fields=["status", "paused_at_stage", "updated_at"])
        render_clip.delay(
            str(clip_render.candidate_id),
            clip_render_id=str(clip_render.pk),
            start_from_stage=next_stage,
        )
        response = HttpResponse(status=204)
        response["HX-Redirect"] = f"/app/clipping/renders/{render_id}/"
        return response
