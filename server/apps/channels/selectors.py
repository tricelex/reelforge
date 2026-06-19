"""Read-only query helpers for channels."""

from server.apps.channels.logic.value_objects import (
    ChannelBrandingPayload,
    ChannelDetailPayload,
    ChannelListPayload,
    ChannelSummaryPayload,
    NicheConfigPayload,
)
from server.apps.channels.models import Channel, ChannelBranding, NicheConfig
from server.common.pagination import paginate_queryset


def _iso(dt: object) -> str | None:
    if dt is None:
        return None
    return str(dt.isoformat())  # type: ignore[attr-defined]


def _to_summary(channel: Channel) -> ChannelSummaryPayload:
    return ChannelSummaryPayload(
        id=str(channel.id),
        name=channel.name,
        kind=channel.kind,
        publish_mode=channel.publish_mode,
        is_active=channel.is_active,
        gates=list(channel.gates),
    )


def list_channels(
    *,
    active_only: bool = False,
    cursor: str | None = None,
    limit: int = 20,
) -> ChannelListPayload:
    """Return channels with cursor pagination."""
    qs = Channel.objects.order_by('-created_at', '-id')
    if active_only:
        qs = qs.filter(is_active=True)
    rows, next_cursor, total = paginate_queryset(
        qs,
        cursor=cursor,
        limit=limit,
    )
    return ChannelListPayload(
        items=[_to_summary(ch) for ch in rows],
        next_cursor=next_cursor,
        total=total,
    )


def get_channel_detail(channel_id: str) -> ChannelDetailPayload:
    """Return full channel detail."""
    channel = Channel.objects.get(id=channel_id)
    return ChannelDetailPayload(
        id=str(channel.id),
        name=channel.name,
        kind=channel.kind,
        publish_mode=channel.publish_mode,
        gates=list(channel.gates),
        character_design_mode=channel.character_design_mode,
        default_budget_usd=(
            str(channel.default_budget_usd)
            if channel.default_budget_usd is not None
            else None
        ),
        voice_id=channel.voice_id,
        stability=channel.stability,
        similarity_boost=channel.similarity_boost,
        wpm=channel.wpm,
        is_active=channel.is_active,
    )


def get_channel_branding(channel_id: str) -> ChannelBrandingPayload:
    """Return branding config, creating defaults if missing."""
    channel = Channel.objects.get(id=channel_id)
    branding, _ = ChannelBranding.objects.get_or_create(channel=channel)
    return ChannelBrandingPayload(
        channel_id=str(channel.id),
        intro_asset_id=(
            str(branding.intro_id) if branding.intro_id else None
        ),
        outro_asset_id=(
            str(branding.outro_id) if branding.outro_id else None
        ),
        watermark_asset_id=(
            str(branding.watermark_id) if branding.watermark_id else None
        ),
        watermark_position=branding.watermark_position,
        watermark_opacity=branding.watermark_opacity,
        caption_style_asset_id=(
            str(branding.caption_style_id)
            if branding.caption_style_id
            else None
        ),
        font_asset_ids=[str(f.id) for f in branding.fonts.all()],
        music_pool_tags=list(branding.music_pool_tags),
        thumbnail_palette=dict(branding.thumbnail_palette),
    )


def get_niche_config(channel_id: str) -> NicheConfigPayload:
    """Return niche config, creating defaults if missing."""
    niche, _ = NicheConfig.objects.get_or_create(channel_id=channel_id)
    return NicheConfigPayload(
        channel_id=str(niche.channel_id),
        format_id=str(niche.format_id) if niche.format_id else None,
        audience=niche.audience,
        angle=niche.angle,
        banned_topics=list(niche.banned_topics),
        lore_document=niche.lore_document,
    )
