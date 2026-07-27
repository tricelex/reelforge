"""Business logic for pipeline run lifecycle."""

import asyncio
import datetime as dt
import uuid
from typing import TYPE_CHECKING, final

import attrs
import django.utils.timezone as tz
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction

from server.apps.pipelines.blueprint_validation import resolve_blueprint_name
from server.apps.pipelines.logic.events import PipelineRunCreated
from server.apps.pipelines.logic.value_objects import (
    ClipRunOptionsPayload,
    RunCreatePayload,
    RunDetailPayload,
    SseTokenPayload,
)
from server.apps.pipelines.selectors import get_run_detail
from server.apps.pipelines.enqueue import (
    kiq_advance_pipeline,
    kiq_execute_stage,
)
from server.common.events import EventBus

if TYPE_CHECKING:
    from server.apps.channels.models import Channel

_IDEMPOTENCY_TTL = 60 * 60 * 24
_SSE_TOKEN_MAX_AGE = 300
_SSE_SIGNER_SALT = 'pipeline-sse-token'


def build_prompt_overrides_snapshot(channel: 'Channel') -> dict[str, str]:
    """Resolve a channel's StoryFormat prompt overrides to version ids.

    ``StoryFormat.prompt_overrides`` maps a stage key to a *template* key.
    Each is resolved to the currently-active PromptVersion id so the run is
    pinned to an immutable version. Overrides naming an unknown template are
    skipped, falling back to the global default for that stage.
    """
    from server.apps.prompts.models import PromptVersion  # noqa: PLC0415

    niche = getattr(channel, 'niche_config', None)
    fmt = getattr(niche, 'format', None) if niche else None
    overrides = getattr(fmt, 'prompt_overrides', None) or {}
    if not isinstance(overrides, dict):
        return {}

    resolved: dict[str, str] = {}
    for stage_key, template_key in overrides.items():
        version_id = (
            PromptVersion.objects
            .filter(template__key=str(template_key), is_active=True)
            .values_list('id', flat=True)
            .first()
        )
        if version_id is not None:
            resolved[str(stage_key)] = str(version_id)
    return resolved


def _initial_prompt_snapshot(
    resolved_prompts: dict[str, str],
) -> dict[str, object]:
    """Seed a fresh run's prompt_snapshot with any resolved overrides."""
    return {'prompts': resolved_prompts} if resolved_prompts else {}


@final
@attrs.define(slots=True, frozen=True)
class PipelineRunService:
    """Create and control pipeline runs."""

    _events: EventBus

    def create(
        self,
        payload: RunCreatePayload,
        *,
        idempotency_key: str | None = None,
    ) -> RunDetailPayload:
        """Create a run, snapshot its blueprint, and kick the orchestrator."""
        if idempotency_key:
            cached = cache.get(f'idempotency:{idempotency_key}')
            if cached:
                return get_run_detail(str(cached))

        run_id = self._create_run_sync(payload)
        if idempotency_key:
            cache.set(
                f'idempotency:{idempotency_key}',
                run_id,
                timeout=_IDEMPOTENCY_TTL,
            )
        self._events.emit(
            PipelineRunCreated(run_id=run_id, channel_id=payload.channel_id),
        )
        transaction.on_commit(lambda: kiq_advance_pipeline(run_id))
        return get_run_detail(run_id)

    def cancel(self, run_id: str) -> RunDetailPayload:
        """Cancel a run and mark in-flight stages cancelled."""
        from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
            _cancel_run_sync,
            publish_sse,
        )

        _cancel_run_sync(run_id)
        asyncio.run(publish_sse(run_id, {'type': 'run.cancelled'}))
        return get_run_detail(run_id)

    def pause(self, run_id: str) -> RunDetailPayload:
        """Pause a run — orchestrator stops enqueueing new stages."""
        from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
            _pause_run_sync,
            publish_sse,
        )

        _pause_run_sync(run_id)
        asyncio.run(publish_sse(run_id, {'type': 'run.paused'}))
        return get_run_detail(run_id)

    def resume(self, run_id: str) -> RunDetailPayload:
        """Resume a paused run and re-evaluate the DAG."""
        from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
            _resume_run_sync,
        )

        _resume_run_sync(run_id)
        kiq_advance_pipeline(run_id)
        return get_run_detail(run_id)

    def rerun_stage(
        self,
        run_id: str,
        stage_key: str,
        *,
        shard_indices: list[int] | None = None,
    ) -> RunDetailPayload:
        """Mark a stage stale and enqueue a fresh attempt."""
        from server.apps.pipelines.services.orchestrator import (  # noqa: PLC0415
            _rerun_stage_sync,
            publish_sse,
        )

        to_enqueue = _rerun_stage_sync(run_id, stage_key, shard_indices)

        for exec_id in to_enqueue:
            kiq_execute_stage(exec_id)
        asyncio.run(
            publish_sse(
                run_id,
                {'type': 'stage.rerun', 'stage_key': stage_key},
            ),
        )
        return get_run_detail(run_id)

    def issue_sse_token(self, run_id: str) -> SseTokenPayload:
        """Mint a short-lived signed token for SSE subscription."""
        from django.core.signing import TimestampSigner  # noqa: PLC0415

        from server.apps.pipelines.models import PipelineRun  # noqa: PLC0415

        PipelineRun.objects.get(id=uuid.UUID(run_id))
        signer = TimestampSigner(salt=_SSE_SIGNER_SALT)
        token = signer.sign(run_id)
        expires_at = tz.now() + dt.timedelta(seconds=_SSE_TOKEN_MAX_AGE)
        return SseTokenPayload(
            token=token,
            expires_at=expires_at.isoformat(),
        )

    @staticmethod
    def validate_sse_token(token: str, run_id: str) -> bool:
        """Return True when token is valid for the given run."""
        from django.core.signing import (  # noqa: PLC0415
            BadSignature,
            SignatureExpired,
            TimestampSigner,
        )

        signer = TimestampSigner(salt=_SSE_SIGNER_SALT)
        try:
            unsigned = signer.unsign(token, max_age=_SSE_TOKEN_MAX_AGE)
        except (BadSignature, SignatureExpired):
            return False
        return unsigned == run_id

    def _create_run_sync(self, payload: RunCreatePayload) -> str:
        from server.apps.channels.models import (  # noqa: PLC0415
            Channel,
            ChannelKind,
        )
        from server.apps.clips.source_services import (  # noqa: PLC0415
            ClipSourceService,
            display_topic_for_source,
        )
        from server.apps.pipelines.models import (  # noqa: PLC0415
            PipelineBlueprint,
            PipelineRun,
            RunStatus,
        )

        try:
            channel = Channel.objects.get(id=uuid.UUID(payload.channel_id))
        except ObjectDoesNotExist as exc:
            msg = f'Channel not found: {payload.channel_id}'
            raise ValidationError(msg) from exc

        topic = payload.topic
        resolved_prompts = build_prompt_overrides_snapshot(channel)
        prompt_snapshot: dict[str, object] = _initial_prompt_snapshot(
            resolved_prompts,
        )
        source_service = ClipSourceService()
        if payload.source_id:
            if payload.topic:
                msg = 'Provide either topic or source_id, not both'
                raise ValidationError(msg)
            if channel.kind != ChannelKind.CLIPPING:
                msg = 'source_id requires a CLIPPING channel'
                raise ValidationError(msg)
        elif not topic:
            msg = 'topic or source_id is required'
            raise ValidationError(msg)

        blueprint_name = resolve_blueprint_name(
            channel_kind=channel.kind,
            channel_default=channel.default_blueprint_name or None,
            run_override=payload.blueprint_name,
        )
        blueprint = PipelineBlueprint.objects.get(
            name=blueprint_name,
            is_active=True,
        )

        clip_options = _normalize_clip_options(
            payload.clip_options,
            auto_approve=payload.auto_approve,
        )

        if payload.source_id:
            with transaction.atomic():
                clip_source = source_service.prepare_for_run(
                    channel_id=payload.channel_id,
                    source_id=payload.source_id,
                )
                topic = display_topic_for_source(clip_source)
                prompt_snapshot = {
                    'source_title': clip_source.title,
                    'source_id': str(clip_source.id),
                    'clip_options': clip_options,
                    'prompts': resolved_prompts,
                }
                run = PipelineRun.objects.create(
                    channel=channel,
                    blueprint=blueprint,
                    blueprint_snapshot=blueprint.graph,
                    topic=topic,
                    prompt_snapshot=prompt_snapshot,
                    status=RunStatus.PENDING,
                    source_idea_id=(
                        uuid.UUID(payload.source_idea_id)
                        if payload.source_idea_id
                        else None
                    ),
                )
                source_service.link_run(clip_source, str(run.id))
            return str(run.id)

        run = PipelineRun.objects.create(
            channel=channel,
            blueprint=blueprint,
            blueprint_snapshot=blueprint.graph,
            topic=topic,
            prompt_snapshot=prompt_snapshot,
            status=RunStatus.PENDING,
            source_idea_id=(
                uuid.UUID(payload.source_idea_id)
                if payload.source_idea_id
                else None
            ),
        )
        return str(run.id)


def _normalize_clip_options(
    raw: ClipRunOptionsPayload | dict[str, object] | None,
    *,
    auto_approve: bool = False,
) -> dict[str, object]:
    """Normalize clipping run options into a JSON-safe snapshot dict."""
    if raw is None:
        opts: dict[str, object] = {}
    elif isinstance(raw, ClipRunOptionsPayload):
        opts = {
            'genre': raw.genre,
            'clip_length': raw.clip_length,
            'moments_prompt': raw.moments_prompt,
            'timeframe_start': raw.timeframe_start,
            'timeframe_end': raw.timeframe_end,
            'custom_min_sec': raw.custom_min_sec,
            'custom_max_sec': raw.custom_max_sec,
            'auto_headline': raw.auto_headline,
            'candidate_count': raw.candidate_count,
            'brand_template_id': raw.brand_template_id,
            'auto_approve': raw.auto_approve,
        }
    else:
        opts = dict(raw)
    if auto_approve:
        opts['auto_approve'] = True
    return {
        'genre': str(opts.get('genre') or 'auto'),
        'clip_length': str(opts.get('clip_length') or 'auto'),
        'moments_prompt': str(opts.get('moments_prompt') or '')[:2000],
        'timeframe_start': opts.get('timeframe_start'),
        'timeframe_end': opts.get('timeframe_end'),
        'custom_min_sec': opts.get('custom_min_sec'),
        'custom_max_sec': opts.get('custom_max_sec'),
        'auto_headline': bool(opts.get('auto_headline', True)),
        'candidate_count': int(opts.get('candidate_count') or 5),
        'brand_template_id': opts.get('brand_template_id'),
        'auto_approve': bool(opts.get('auto_approve', False)),
    }
