"""Read-only query helpers for channels."""

import django.utils.timezone as tz
from django.db.models import Count, Max, Q, Sum

from server.apps.channels.logic.value_objects import (
    ChannelBrandingPayload,
    ChannelDetailPayload,
    ChannelListPayload,
    ChannelSummaryPayload,
    NicheConfigPayload,
)
from server.apps.channels.models import Channel, ChannelBranding, NicheConfig
from server.apps.pipelines.models import RunStatus
from server.apps.publishing.models import PublishStatus
from server.common.pagination import paginate_queryset

_IN_FLIGHT_STATUSES = {
    RunStatus.PENDING,
    RunStatus.RUNNING,
    RunStatus.AWAITING_REVIEW,
    RunStatus.BUDGET_HOLD,
    RunStatus.PUBLISHING,
}


def _iso(dt: object) -> str | None:
    if dt is None:
        return None
    return str(dt.isoformat())  # type: ignore[attr-defined]


def _youtube_status(channel: Channel) -> str:
    try:
        cred = channel.youtube_credential
    except Exception:  # noqa: BLE001
        return 'disconnected'
    if cred.token_expiry and cred.token_expiry < tz.now():
        return 'expired'
    return 'connected'


def _to_summary(channel: Channel) -> ChannelSummaryPayload:
    niche = getattr(channel, 'niche_config', None)
    niche_id = str(niche.id) if niche is not None else None
    niche_angle = niche.angle if niche is not None else ''
    published_videos = int(getattr(channel, 'published_videos', 0))
    active_runs = int(getattr(channel, 'active_runs', 0))
    total_spend = getattr(channel, 'total_spend', None)
    total_spend_usd = f'{total_spend:.4f}' if total_spend is not None else '0.0000'
    last_activity = getattr(channel, 'last_activity', None)
    return ChannelSummaryPayload(
        id=str(channel.id),
        name=channel.name,
        kind=channel.kind,
        publish_mode=channel.publish_mode,
        is_active=channel.is_active,
        gates=list(channel.gates),
        niche_id=niche_id,
        niche_angle=niche_angle,
        published_videos=published_videos,
        active_runs=active_runs,
        total_spend_usd=total_spend_usd,
        last_activity_at=_iso(last_activity),
        youtube_status=_youtube_status(channel),
    )


def list_channels(
    *,
    active_only: bool = False,
    cursor: str | None = None,
    limit: int = 20,
) -> ChannelListPayload:
    """Return channels with cursor pagination."""
    qs = (
        Channel.objects
        .select_related('niche_config', 'youtube_credential')
        .annotate(
            published_videos=Count(
                'publish_jobs',
                filter=Q(publish_jobs__status=PublishStatus.COMPLETED),
                distinct=True,
            ),
            active_runs=Count(
                'runs',
                filter=Q(runs__status__in=_IN_FLIGHT_STATUSES),
                distinct=True,
            ),
            total_spend=Sum('runs__total_cost_usd'),
            last_activity=Max('runs__updated_at'),
        )
        .order_by('-created_at', '-id')
    )
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
        intro_asset_id=(str(branding.intro_id) if branding.intro_id else None),
        outro_asset_id=(str(branding.outro_id) if branding.outro_id else None),
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
        id=str(niche.id),
        channel_id=str(niche.channel_id),
        format_id=str(niche.format_id) if niche.format_id else None,
        audience=niche.audience,
        angle=niche.angle,
        banned_topics=list(niche.banned_topics),
        lore_document=niche.lore_document,
    )
