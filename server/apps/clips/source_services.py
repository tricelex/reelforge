"""Business logic for clip source registration and probing."""

import uuid
from typing import final

import attrs
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from server.apps.assets.models import LibraryAsset
from server.apps.channels.models import Channel, ChannelKind
from server.apps.clips.logic.constants import ClipSourceStatus, ClipSourceType
from server.apps.clips.logic.value_objects import (
    ClipSourceCreatePayload,
    ClipSourceListPayload,
    ClipSourcePayload,
)
from server.apps.clips.models import ClipCampaign, ClipSource
from server.apps.clips.source_selectors import get_clip_source, list_clip_sources
from server.apps.clips.tasks import _probe_clip_source_sync, probe_clip_source_task
from server.common.taskiq_sender import kiq_task


def _require_remote_url(source_type: str, url: str) -> None:
    if source_type in (ClipSourceType.YOUTUBE, ClipSourceType.RSS) and not url:
        msg = 'url is required for youtube and rss sources'
        raise ValidationError(msg)


def _resolve_topic(source: ClipSource) -> str:
    if source.source_type == ClipSourceType.UPLOAD:
        if source.library_asset_id is None:
            msg = 'Upload source missing library_asset_id'
            raise ValidationError(msg)
        return str(source.library_asset_id)
    if not source.url:
        msg = 'Source URL is required'
        raise ValidationError(msg)
    return source.url


@final
@attrs.define(slots=True, frozen=True)
class ClipSourceService:
    """Register and probe clip sources."""

    def list_sources(
        self,
        *,
        channel_id: str | None = None,
        status: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> ClipSourceListPayload:
        """Return clip sources."""
        return list_clip_sources(
            channel_id=channel_id,
            status=status,
            cursor=cursor,
            limit=limit,
        )

    def get_source(self, source_id: str) -> ClipSourcePayload:
        """Return one clip source."""
        return get_clip_source(source_id)

    def create(self, payload: ClipSourceCreatePayload) -> ClipSourcePayload:
        """Register a clip source and start probing when needed."""
        try:
            channel = Channel.objects.get(id=uuid.UUID(payload.channel_id))
        except ObjectDoesNotExist as exc:
            msg = f'Channel not found: {payload.channel_id}'
            raise ValidationError(msg) from exc
        if channel.kind != ChannelKind.CLIPPING:
            msg = 'Clip sources require a CLIPPING channel'
            raise ValidationError(msg)

        campaign = None
        if payload.campaign_id:
            try:
                campaign = ClipCampaign.objects.get(
                    id=uuid.UUID(payload.campaign_id),
                    channel=channel,
                )
            except ObjectDoesNotExist as exc:
                msg = f'Campaign not found: {payload.campaign_id}'
                raise ValidationError(msg) from exc

        source_type = payload.source_type
        if source_type not in ClipSourceType.values:
            msg = f'Invalid source_type: {source_type}'
            raise ValidationError(msg)

        library_asset_id = None
        title = ''
        duration_sec = None
        status = ClipSourceStatus.INGESTING
        url = payload.url.strip()
        _require_remote_url(source_type, url)

        if source_type == ClipSourceType.UPLOAD:
            if not payload.library_asset_id:
                msg = 'library_asset_id is required for upload sources'
                raise ValidationError(msg)
            try:
                asset = LibraryAsset.objects.get(
                    id=uuid.UUID(payload.library_asset_id),
                )
            except ObjectDoesNotExist as exc:
                msg = f'Library asset not found: {payload.library_asset_id}'
                raise ValidationError(msg) from exc
            library_asset_id = asset.id
            title = asset.name
            status = ClipSourceStatus.READY

        source = ClipSource.objects.create(
            channel=channel,
            campaign=campaign,
            source_type=source_type,
            url=url,
            library_asset_id=library_asset_id,
            title=title,
            duration_sec=duration_sec,
            status=status,
        )

        if source_type in (ClipSourceType.YOUTUBE, ClipSourceType.RSS):
            kiq_task(probe_clip_source_task, str(source.id))
        return get_clip_source(str(source.id))

    def link_run(self, source_id: str, run_id: str) -> None:
        """Associate a pipeline run with a clip source."""
        source = ClipSource.objects.get(id=uuid.UUID(source_id))
        source.run_id = uuid.UUID(run_id)
        source.save(update_fields=['run_id', 'updated_at'])

    def resolve_topic_for_run(self, source_id: str) -> str:
        """Return the topic string for PipelineRun.create from a source."""
        source = ClipSource.objects.get(id=uuid.UUID(source_id))
        if source.status != ClipSourceStatus.READY:
            msg = f'Clip source is not ready: {source.status}'
            raise ValidationError(msg)
        return _resolve_topic(source)

    def probe_now(self, source_id: str) -> ClipSourcePayload:
        """Synchronous probe helper for tests."""
        _probe_clip_source_sync(source_id)
        return get_clip_source(source_id)
