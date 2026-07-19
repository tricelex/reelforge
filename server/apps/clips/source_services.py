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
from server.apps.clips.source_selectors import (
    get_clip_source,
    list_clip_sources,
)
from server.apps.clips.tasks import (
    _probe_clip_source_sync,
    probe_clip_source_task,
)
from server.common.exceptions import ConflictError
from server.common.taskiq_sender import kiq_task


def _require_remote_url(source_type: str, url: str) -> None:
    if source_type in (ClipSourceType.YOUTUBE, ClipSourceType.RSS) and not url:
        msg = 'url is required for youtube and rss sources'
        raise ValidationError(msg)


def resolve_ingest_key(source: ClipSource) -> str:
    """Return the ingest key (URL or library asset id) for a clip source."""
    if source.source_type == ClipSourceType.UPLOAD:
        if source.library_asset_id is None:
            msg = 'Upload source missing library_asset_id'
            raise ValidationError(msg)
        return str(source.library_asset_id)
    if not source.url:
        msg = 'Source URL is required'
        raise ValidationError(msg)
    return source.url


def display_topic_for_source(source: ClipSource) -> str:
    """Return a human-readable topic for a clip source run."""
    if source.title:
        return source.title
    if source.url:
        return source.url
    if source.library_asset_id:
        return str(source.library_asset_id)
    return 'Untitled clip source'


def _clip_options_dict(options: object | None) -> dict[str, object]:
    if options is None:
        return {}
    if hasattr(options, '__struct_fields__'):
        return {
            field: getattr(options, field)
            for field in options.__struct_fields__  # type: ignore[attr-defined]
        }
    if isinstance(options, dict):
        return dict(options)
    return {}


def _optional_float(value: object) -> float | None:
    if value is None or value == '':  # noqa: PLC1901
        return None
    return float(value)  # type: ignore[arg-type]


def _maybe_auto_start_run(source: ClipSource) -> None:
    """Create a clipping run when the source is ready and auto_start is set."""
    if not source.auto_start:
        return
    if source.status != ClipSourceStatus.READY:
        return
    if source.run_id is not None:
        return

    from server.apps.pipelines.logic.value_objects import (  # noqa: PLC0415
        ClipRunOptionsPayload,
        RunCreatePayload,
    )
    from server.apps.pipelines.services.pipeline_run import (  # noqa: PLC0415
        PipelineRunService,
    )
    from server.common.container import container  # noqa: PLC0415

    opts = source.pending_run_options or {}
    clip_options = ClipRunOptionsPayload(
        genre=str(opts.get('genre') or 'auto'),
        clip_length=str(opts.get('clip_length') or 'auto'),
        moments_prompt=str(opts.get('moments_prompt') or ''),
        timeframe_start=_optional_float(opts.get('timeframe_start')),
        timeframe_end=_optional_float(opts.get('timeframe_end')),
        custom_min_sec=_optional_float(opts.get('custom_min_sec')),
        custom_max_sec=_optional_float(opts.get('custom_max_sec')),
        auto_headline=bool(opts.get('auto_headline', True)),
        candidate_count=int(opts.get('candidate_count') or 5),
        brand_template_id=(
            str(opts['brand_template_id'])
            if opts.get('brand_template_id')
            else None
        ),
        auto_approve=bool(opts.get('auto_approve', False)),
    )
    container.resolve(PipelineRunService).create(
        RunCreatePayload(
            channel_id=str(source.channel_id),
            source_id=str(source.id),
            clip_options=clip_options,
            auto_approve=clip_options.auto_approve,
        ),
    )
    source.auto_start = False
    source.pending_run_options = {}
    source.save(
        update_fields=['auto_start', 'pending_run_options', 'updated_at'],
    )


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
            auto_start=payload.auto_start,
            pending_run_options=_clip_options_dict(payload.clip_options),
        )

        if source_type in (ClipSourceType.YOUTUBE, ClipSourceType.RSS):
            kiq_task(probe_clip_source_task, str(source.id))
        elif payload.auto_start:
            _maybe_auto_start_run(source)
        return get_clip_source(str(source.id))

    def prepare_for_run(
        self,
        *,
        channel_id: str,
        source_id: str,
    ) -> ClipSource:
        """Validate and lock a clip source before starting a pipeline run.

        Caller must hold ``transaction.atomic()`` so the row lock persists
        through run creation and ``link_run``.
        """
        try:
            source = ClipSource.objects.select_for_update().get(
                id=uuid.UUID(source_id),
            )
        except ObjectDoesNotExist as exc:
            msg = f'Clip source not found: {source_id}'
            raise ValidationError(msg) from exc

        if str(source.channel_id) != channel_id:
            msg = 'source_id does not belong to channel_id'
            raise ValidationError(msg)

        if source.status != ClipSourceStatus.READY:
            msg = f'Clip source is not ready: {source.status}'
            raise ValidationError(msg)

        if source.run_id is not None:
            msg = 'Clip source already has a pipeline run'
            raise ConflictError(msg)

        return source

    def link_run(self, source: ClipSource, run_id: str) -> None:
        """Associate a pipeline run with a clip source."""
        source.run_id = uuid.UUID(run_id)
        source.save(update_fields=['run_id', 'updated_at'])

    def resolve_topic_for_run(self, source_id: str) -> str:
        """Return the topic string for PipelineRun.create from a source."""
        source = ClipSource.objects.get(id=uuid.UUID(source_id))
        if source.status != ClipSourceStatus.READY:
            msg = f'Clip source is not ready: {source.status}'
            raise ValidationError(msg)
        return resolve_ingest_key(source)

    def probe_now(self, source_id: str) -> ClipSourcePayload:
        """Synchronous probe helper for tests."""
        _probe_clip_source_sync(source_id)
        return get_clip_source(source_id)
