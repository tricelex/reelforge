"""Read-only analytics API endpoints."""

from django.http import HttpRequest, JsonResponse

from server.apps.analytics import selectors


async def run_cost_view(request: HttpRequest, run_id: str) -> JsonResponse:
    """Return cost breakdown for a single pipeline run."""
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    data = await sync_to_async(selectors.get_run_cost_breakdown)(run_id)
    return JsonResponse(data)


async def channel_roi_view(
    request: HttpRequest,
    channel_id: str,
) -> JsonResponse:
    """Return channel-level ROI aggregates."""
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    data = await sync_to_async(selectors.get_channel_roi)(channel_id)
    return JsonResponse(data)


async def channel_stages_view(
    request: HttpRequest,
    channel_id: str,
) -> JsonResponse:
    """Return per-stage performance metrics for a channel."""
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    rows = await sync_to_async(selectors.get_stage_performance)(channel_id)
    return JsonResponse({'stage_performance': rows})
