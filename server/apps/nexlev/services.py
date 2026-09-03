"""NexLev read service — records-first, staleness-aware, per section."""

import hashlib
import json
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
    NexLevChannelAnalysisResult,
    NexLevChannelAnalytics,
    NexLevComment,
    NexLevNicheOverview,
    NexLevOutlierVideo,
    NexLevScriptStage,
    NexLevSearchResultItem,
    NexLevSimilarChannel,
    NexLevSuggestedTopic,
    NexLevTitleFormatGroup,
    NexLevTranscriptSegment,
    NexLevVideoDetails,
)
from server.apps.nexlev.models import (
    NexLevChannelRecord,
    NexLevSearchCacheEntry,
    NexLevVideoRecord,
)


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


def _get_or_create_video_record(video_id: str) -> NexLevVideoRecord:
    record, _ = NexLevVideoRecord.objects.get_or_create(video_id=video_id)
    return record


def _save_video_record(record: NexLevVideoRecord, *, fields: list[str]) -> None:
    record.save(update_fields=[*fields, 'updated_at'])


def _search_cache_key(query: str, search_type: str | None) -> str:
    raw = json.dumps({'query': query, 'type': search_type}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_fresh_search_cache_entry(
    cache_key: str,
) -> NexLevSearchCacheEntry | None:
    cutoff = timezone.now() - constants.SEARCH_CACHE_TTL
    return NexLevSearchCacheEntry.objects.filter(
        cache_key=cache_key,
        fetched_at__gte=cutoff,
    ).first()


def _upsert_search_cache_entry(
    cache_key: str,
    payload: list[dict[str, object]],
) -> None:
    NexLevSearchCacheEntry.objects.update_or_create(
        cache_key=cache_key,
        defaults={
            'payload': payload,
            'fetched_at': timezone.now(),
            'quota_spent': constants.QUOTA_COST_SEARCH,
        },
    )


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
        stale = force_refresh or is_stale(
            record.about_fetched_at,
            window=constants.ABOUT_STALE_AFTER,
        )
        if not stale:
            try:
                return msgspec.convert(
                    record.about,
                    type=NexLevChannelAbout,
                    strict=False,
                )
            except msgspec.ValidationError:
                # Cached row predates a provider-shape fix; refetch it.
                pass
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
        return msgspec.convert(
            record.about,
            type=NexLevChannelAbout,
            strict=False,
        )

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
            strict=False,
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
        return msgspec.convert(
            record.analytics,
            type=NexLevChannelAnalytics,
            strict=False,
        )

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
            strict=False,
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
        stale = force_refresh or is_stale(
            record.niche_overview_fetched_at,
            window=constants.NICHE_OVERVIEW_STALE_AFTER,
        )
        if not stale:
            try:
                return msgspec.convert(
                    record.niche_overview,
                    type=NexLevNicheOverview,
                    strict=False,
                )
            except msgspec.ValidationError:
                # Cached row predates a provider-shape fix; refetch it.
                pass
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
            strict=False,
        )

    async def get_video_details(
        self,
        video_id: str,
        *,
        force_refresh: bool = False,
    ) -> NexLevVideoDetails:
        """Return video details; content is immutable, long staleness."""
        record = await sync_to_async(_get_or_create_video_record)(video_id)
        stale = force_refresh or is_stale(
            record.details_fetched_at,
            window=constants.VIDEO_STALE_AFTER,
        )
        if not stale:
            try:
                return msgspec.convert(
                    record.details,
                    type=NexLevVideoDetails,
                    strict=False,
                )
            except msgspec.ValidationError:
                # Cached row predates a provider-shape fix; refetch it.
                pass
        raw = await nexlev_client.get_video_details(
            video_id,
            api_key=settings.NEXLEV_API_KEY,
            base_url=settings.NEXLEV_BASE_URL,
        )
        record.details = raw
        record.details_fetched_at = timezone.now()
        record.quota_spent += constants.QUOTA_COST_VIDEO_DETAILS
        await sync_to_async(_save_video_record)(
            record,
            fields=['details', 'details_fetched_at', 'quota_spent'],
        )
        return msgspec.convert(
            record.details,
            type=NexLevVideoDetails,
            strict=False,
        )

    async def get_video_transcript(
        self,
        video_id: str,
        *,
        force_refresh: bool = False,
    ) -> list[NexLevTranscriptSegment]:
        """Return the transcript; content is immutable, long staleness."""
        record = await sync_to_async(_get_or_create_video_record)(video_id)
        if force_refresh or is_stale(
            record.transcript_fetched_at,
            window=constants.VIDEO_STALE_AFTER,
        ):
            raw = await nexlev_client.get_video_transcript(
                video_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.transcript = raw
            record.transcript_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_VIDEO_TRANSCRIPT
            await sync_to_async(_save_video_record)(
                record,
                fields=[
                    'transcript',
                    'transcript_fetched_at',
                    'quota_spent',
                ],
            )
        return msgspec.convert(
            record.transcript or [],
            type=list[NexLevTranscriptSegment],
            strict=False,
        )

    async def get_video_comments(
        self,
        video_id: str,
        *,
        force_refresh: bool = False,
    ) -> list[NexLevComment]:
        """Return top comments; content is immutable, long staleness."""
        record = await sync_to_async(_get_or_create_video_record)(video_id)
        if force_refresh or is_stale(
            record.comments_fetched_at,
            window=constants.VIDEO_STALE_AFTER,
        ):
            raw = await nexlev_client.get_video_comments(
                video_id,
                api_key=settings.NEXLEV_API_KEY,
                base_url=settings.NEXLEV_BASE_URL,
            )
            record.comments = raw
            record.comments_fetched_at = timezone.now()
            record.quota_spent += constants.QUOTA_COST_VIDEO_COMMENTS
            await sync_to_async(_save_video_record)(
                record,
                fields=['comments', 'comments_fetched_at', 'quota_spent'],
            )
        return msgspec.convert(
            record.comments or [],
            type=list[NexLevComment],
            strict=False,
        )

    async def search_youtube(
        self,
        query: str,
        *,
        search_type: str | None = None,
    ) -> list[NexLevSearchResultItem]:
        """Return live YouTube search results, short-TTL cached by query."""
        cache_key = _search_cache_key(query, search_type)
        cached = await sync_to_async(_get_fresh_search_cache_entry)(cache_key)
        if cached is not None:
            return msgspec.convert(
                cached.payload,
                type=list[NexLevSearchResultItem],
                strict=False,
            )
        raw = await nexlev_client.search_youtube(
            query,
            api_key=settings.NEXLEV_API_KEY,
            base_url=settings.NEXLEV_BASE_URL,
            search_type=search_type,
        )
        await sync_to_async(_upsert_search_cache_entry)(cache_key, raw)
        return msgspec.convert(
            raw,
            type=list[NexLevSearchResultItem],
            strict=False,
        )

    async def create_channel_analysis_job(self, channel_id: str) -> str:
        """Kick off NexLev's async Deep Analysis job.

        Always live — never staleness-checked, since this is an explicit
        operator action.
        """
        return await nexlev_client.create_channel_analysis_job(
            channel_id,
            api_key=settings.NEXLEV_API_KEY,
            base_url=settings.NEXLEV_BASE_URL,
        )

    async def get_channel_analysis_result(
        self,
        nexlev_job_id: str,
        channel_id: str,
    ) -> NexLevChannelAnalysisResult | None:
        """Poll one Deep Analysis job; store the result once completed."""
        raw = await nexlev_client.get_channel_analysis_result(
            nexlev_job_id,
            api_key=settings.NEXLEV_API_KEY,
            base_url=settings.NEXLEV_BASE_URL,
        )
        if raw is None:
            return None
        insights = raw['result']['strategic_insights']
        result = NexLevChannelAnalysisResult(
            suggested_topics=[
                NexLevSuggestedTopic(
                    title=item['title'],
                    description=item.get('description', ''),
                )
                for item in insights['suggested_topics']['topics']
            ],
            script_blueprint=[
                NexLevScriptStage(
                    stage=item['stage'],
                    purpose=item.get('purpose', ''),
                    recommended_length_seconds=item.get(
                        'recommended_length_seconds',
                        0,
                    ),
                    winning_formula=item.get('winning_formula', ''),
                )
                for item in insights['script_blueprint']['recommended_stages']
            ],
            title_format_groups=[
                NexLevTitleFormatGroup(
                    format_name=item['format_name'],
                    format_description=item.get('format_description', ''),
                    video_count=item.get('video_count', 0),
                )
                for item in insights['title_format_strategy']['format_groups']
            ],
        )
        record = await sync_to_async(_get_or_create_channel_record)(
            channel_id,
        )
        record.channel_analysis = msgspec.to_builtins(result)
        record.channel_analysis_fetched_at = timezone.now()
        record.quota_spent += constants.QUOTA_COST_CHANNEL_ANALYSIS_STATUS
        await sync_to_async(_save_channel_record)(
            record,
            fields=[
                'channel_analysis',
                'channel_analysis_fetched_at',
                'quota_spent',
            ],
        )
        return result
