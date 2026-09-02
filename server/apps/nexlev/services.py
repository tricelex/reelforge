"""NexLev read service — records-first, staleness-aware, per section."""

from typing import final

import attrs
import msgspec
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone

from server.apps.nexlev.clients import nexlev_client
from server.apps.nexlev.logic import constants
from server.apps.nexlev.logic.staleness import is_stale
from server.apps.nexlev.logic.value_objects import (
    NexLevChannelAbout,
    NexLevChannelAnalytics,
    NexLevNicheOverview,
    NexLevOutlierVideo,
    NexLevSimilarChannel,
)
from server.apps.nexlev.models import NexLevChannelRecord


def _get_or_create_channel_record(channel_id: str) -> NexLevChannelRecord:
    record, _ = NexLevChannelRecord.objects.get_or_create(
        channel_id=channel_id,
    )
    return record


def _save_channel_record(
    record: NexLevChannelRecord,
    *,
    fields: list[str],
) -> None:
    record.save(update_fields=[*fields, 'updated_at'])


@final
@attrs.define(slots=True, frozen=True)
class NexLevService:
    """Records-first NexLev reads: refetch only stale sections."""

    async def get_channel_about(
        self,
        channel_id: str,
        *,
        force_refresh: bool = False,
    ) -> NexLevChannelAbout:
        """Return channel about-info, refetching only if stale/missing."""
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        if force_refresh or is_stale(
            record.about_fetched_at,
            window=constants.ABOUT_STALE_AFTER,
        ):
            raw = await nexlev_client.get_channel_about(
                channel_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.about = raw
            record.about_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_ABOUT
            await sync_to_async(_save_channel_record)(
                record,
                fields=['about', 'about_fetched_at', 'quota_spent'],
            )
        return msgspec.convert(record.about, type=NexLevChannelAbout)

    async def get_channel_outliers(
        self,
        channel_id: str,
        *,
        force_refresh: bool = False,
    ) -> list[NexLevOutlierVideo]:
        """Return outlier videos, refetching only if stale/missing."""
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        if force_refresh or is_stale(
            record.outliers_fetched_at,
            window=constants.OUTLIERS_STALE_AFTER,
        ):
            raw = await nexlev_client.get_channel_outliers(
                channel_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.outliers = raw
            record.outliers_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_OUTLIERS
            await sync_to_async(_save_channel_record)(
                record,
                fields=['outliers', 'outliers_fetched_at', 'quota_spent'],
            )
        return msgspec.convert(
            record.outliers or [],
            type=list[NexLevOutlierVideo],
        )

    async def get_channel_analytics(
        self,
        channel_id: str,
        *,
        force_refresh: bool = False,
    ) -> NexLevChannelAnalytics:
        """Return channel analytics, refetching only if stale/missing."""
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        if force_refresh or is_stale(
            record.analytics_fetched_at,
            window=constants.ANALYTICS_STALE_AFTER,
        ):
            raw = await nexlev_client.get_channel_analytics(
                channel_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.analytics = raw
            record.analytics_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_ANALYTICS
            await sync_to_async(_save_channel_record)(
                record,
                fields=['analytics', 'analytics_fetched_at', 'quota_spent'],
            )
        return msgspec.convert(record.analytics, type=NexLevChannelAnalytics)

    async def get_similar_channels(
        self,
        channel_id: str,
        *,
        force_refresh: bool = False,
    ) -> list[NexLevSimilarChannel]:
        """Return similar channels, refetching only if stale/missing."""
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        if force_refresh or is_stale(
            record.similar_channels_fetched_at,
            window=constants.SIMILAR_CHANNELS_STALE_AFTER,
        ):
            raw = await nexlev_client.get_similar_channels(
                channel_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.similar_channels = raw
            record.similar_channels_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_SIMILAR_CHANNELS
            await sync_to_async(_save_channel_record)(
                record,
                fields=[
                    'similar_channels',
                    'similar_channels_fetched_at',
                    'quota_spent',
                ],
            )
        return msgspec.convert(
            record.similar_channels or [],
            type=list[NexLevSimilarChannel],
        )

    async def get_niche_overview(
        self,
        channel_id: str,
        *,
        force_refresh: bool = False,
    ) -> NexLevNicheOverview:
        """Return niche overview, refetching only if stale/missing."""
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        if force_refresh or is_stale(
            record.niche_overview_fetched_at,
            window=constants.NICHE_OVERVIEW_STALE_AFTER,
        ):
            raw = await nexlev_client.get_niche_overview(
                channel_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.niche_overview = raw
            record.niche_overview_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_NICHE_OVERVIEW
            await sync_to_async(_save_channel_record)(
                record,
                fields=[
                    'niche_overview',
                    'niche_overview_fetched_at',
                    'quota_spent',
                ],
            )
        return msgspec.convert(
            record.niche_overview,
            type=NexLevNicheOverview,
        )
