from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect
from django.urls import reverse

from ***REMOVED***.channels.models import Channel
from ***REMOVED***.channels.services import ChannelSetupService

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse

logger = logging.getLogger("***REMOVED***.channels")


@staff_member_required
def youtube_oauth_callback(request: HttpRequest) -> HttpResponse:
    """Handle the Google OAuth2 callback after the user authorises access."""
    code = request.GET.get("code", "")
    state = request.GET.get("state", "")

    channel_id: str = request.session.pop("youtube_oauth_channel_id", "")
    expected_state: str = request.session.pop("youtube_oauth_state", "")

    # --- CSRF check ---
    if not state or state != expected_state:
        messages.error(request, "OAuth state mismatch — possible CSRF. Please try again.")
        return redirect(reverse("admin:channels_channel_changelist"))

    if not channel_id:
        messages.error(request, "Session expired — no channel ID found. Please try again.")
        return redirect(reverse("admin:channels_channel_changelist"))

    try:
        channel = Channel.objects.get(pk=channel_id)
    except Channel.DoesNotExist:
        messages.error(request, f"Channel {channel_id} not found.")
        return redirect(reverse("admin:channels_channel_changelist"))

    redirect_uri: str = request.build_absolute_uri(reverse("youtube_oauth_callback"))

    svc = ChannelSetupService(channel)
    try:
        svc.exchange_oauth_code(code=code, redirect_uri=redirect_uri)
        messages.success(
            request,
            f"YouTube OAuth configured for '{channel.name}' (channel ID: {channel.youtube_channel_id}).",
        )
        logger.info(
            "YouTube OAuth configured successfully",
            extra={
                "channel_id": str(channel.id),
                "youtube_channel_id": channel.youtube_channel_id,
            },
        )
    except Exception as exc:
        messages.error(request, f"OAuth setup failed for '{channel.name}': {exc}")
        logger.exception(
            "YouTube OAuth exchange failed",
            extra={"channel_id": str(channel.id), "error": str(exc)},
        )

    return redirect(reverse("admin:channels_channel_change", args=[channel.pk]))
