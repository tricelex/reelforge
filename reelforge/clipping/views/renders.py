from __future__ import annotations

import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.views.decorators.http import require_POST

from ***REMOVED***.clipping.models import ClipRender
from ***REMOVED***.clipping.tasks import render_clip

logger = logging.getLogger("***REMOVED***.clipping.views")

_TERMINAL_RENDER_STATUSES = frozenset({
    ClipRender.RenderStatus.COMPLETED,
    ClipRender.RenderStatus.FAILED,
    ClipRender.RenderStatus.PAUSED_AT_GATE,
})


@staff_member_required
def render_detail(request: HttpRequest, render_id: str) -> HttpResponse:
    clip_render = get_object_or_404(
        ClipRender.objects.select_related(
            "candidate__clipping_job__channel",
            "candidate__layout_config",
        ).prefetch_related("stage_results"),
        pk=render_id,
    )
    candidate = clip_render.candidate
    layout = getattr(candidate, "layout_config", None)
    is_terminal = clip_render.status in _TERMINAL_RENDER_STATUSES
    stages = list(clip_render.stage_results.order_by("stage_order"))

    return render(
        request,
        "clipping/render_detail.html",
        {
            "render": clip_render,
            "candidate": candidate,
            "layout": layout,
            "stages": stages,
            "is_terminal": is_terminal,
        },
    )


@staff_member_required
def stage_list_partial(request: HttpRequest, render_id: str) -> HttpResponse:
    """HTMX polling target: refreshes the stage list. Self-stopping when render is terminal."""
    clip_render = get_object_or_404(
        ClipRender.objects.prefetch_related("stage_results"),
        pk=render_id,
    )
    is_terminal = clip_render.status in _TERMINAL_RENDER_STATUSES
    stages = list(clip_render.stage_results.order_by("stage_order"))

    return render(
        request,
        "clipping/partials/stage_list.html",
        {
            "render": clip_render,
            "stages": stages,
            "is_terminal": is_terminal,
        },
    )


@staff_member_required
@require_POST
def rerun_from_stage(request: HttpRequest, render_id: str, stage_order: int) -> HttpResponse:
    """Re-run the render pipeline from the given stage order."""
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


@staff_member_required
@require_POST
def resume_render(request: HttpRequest, render_id: str) -> HttpResponse:
    """Continue the pipeline from the stage after the current gate pause."""
    clip_render = get_object_or_404(ClipRender, pk=render_id)
    if clip_render.status != ClipRender.RenderStatus.PAUSED_AT_GATE or clip_render.paused_at_stage is None:
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
