from __future__ import annotations

from rest_framework import serializers

from reelforge.channels.models import SocialAccount


class SocialAccountSerializer(serializers.ModelSerializer[SocialAccount]):
    platform_display = serializers.CharField(
        source="get_platform_display",
        read_only=True,
    )
    channel_id = serializers.UUIDField(source="channel.id", read_only=True)
    channel_name = serializers.CharField(source="channel.name", read_only=True)

    class Meta:
        model = SocialAccount
        fields = [
            "id",
            "platform",
            "platform_display",
            "handle",
            "display_name",
            "is_active",
            "channel_id",
            "channel_name",
            "follower_count",
            "last_sync_at",
        ]
        read_only_fields = [
            "id",
            "platform",
            "platform_display",
            "handle",
            "display_name",
            "is_active",
            "channel_id",
            "channel_name",
            "follower_count",
            "last_sync_at",
        ]
