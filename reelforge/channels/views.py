from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect
from django.urls import reverse
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import extend_schema_view
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.viewsets import GenericViewSet

from ***REMOVED***.channels.models import Channel
from ***REMOVED***.channels.models import SocialAccount
from ***REMOVED***.channels.serializers import SocialAccountSerializer
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
        yt_account = channel.get_youtube_account()
        yt_channel_id = yt_account.account_id if yt_account else "unknown"
        messages.success(
            request,
            f"YouTube OAuth configured for '{channel.name}' (channel ID: {yt_channel_id}).",
        )
        logger.info(
            "YouTube OAuth configured successfully",
            extra={
                "channel_id": str(channel.id),
                "youtube_channel_id": yt_channel_id,
            },
        )
    except Exception as exc:
        messages.error(request, f"OAuth setup failed for '{channel.name}': {exc}")
        logger.exception(
            "YouTube OAuth exchange failed",
            extra={"channel_id": str(channel.id), "error": str(exc)},
        )

    return redirect(reverse("admin:channels_channel_change", args=[channel.pk]))


@extend_schema_view(
    list=extend_schema(
        tags=["social-accounts"],
        summary="List social accounts",
        parameters=[
            OpenApiParameter(
                name="platform",
                description="Filter by platform (YOUTUBE, TIKTOK, INSTAGRAM)",
                required=False,
                type=str,
                enum=["YOUTUBE", "TIKTOK", "INSTAGRAM"],
            ),
            OpenApiParameter(
                name="is_active",
                description="Filter by active status (true/false)",
                required=False,
                type=bool,
            ),
        ],
    ),
    retrieve=extend_schema(
        tags=["social-accounts"],
        summary="Get a social account",
    ),
)
class SocialAccountViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    queryset = SocialAccount.objects.select_related("channel").order_by("channel", "platform")
    serializer_class = SocialAccountSerializer
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        platform = self.request.query_params.get("platform")
        if platform:
            qs = qs.filter(platform=platform)
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")
        return qs
