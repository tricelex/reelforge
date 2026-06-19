"""Business logic for pipeline run lifecycle."""

import asyncio
import datetime as dt
import uuid
from typing import final

import attrs
import django.utils.timezone as tz
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from server.apps.pipelines.logic.events import PipelineRunCreated
from server.apps.pipelines.logic.value_objects import (
    RunCreatePayload,
    RunDetailPayload,
    SseTokenPayload,
)
from server.apps.pipelines.selectors import get_run_detail
from server.common.events import EventBus

_IDEMPOTENCY_TTL = 60 * 60 * 24
_SSE_TOKEN_MAX_AGE = 300
_SSE_SIGNER_SALT = 'pipeline-sse-token'

_BLUEPRINT_BY_KIND: dict[str, str] = {
    'LONGFORM': 'longform_v1',
    'CLIPPING': 'clipping_v1',
    'SHORTS': 'longform_v1',
}


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
        asyncio.run(self._kick_advance(run_id))
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
            advance_pipeline_impl,
        )

        _resume_run_sync(run_id)
        asyncio.run(advance_pipeline_impl(run_id))
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
            execute_stage_kiq,
            publish_sse,
        )

        to_enqueue = _rerun_stage_sync(run_id, stage_key, shard_indices)

        async def _enqueue() -> None:
            for exec_id in to_enqueue:
                await execute_stage_kiq(exec_id)
            await publish_sse(
                run_id,
                {'type': 'stage.rerun', 'stage_key': stage_key},
            )

        asyncio.run(_enqueue())
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
        from server.apps.channels.models import Channel  # noqa: PLC0415
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

        blueprint_name = payload.blueprint_name or _BLUEPRINT_BY_KIND.get(
            channel.kind,
        )
        if blueprint_name is None:
            msg = f'No blueprint mapping for channel kind {channel.kind}'
            raise ValidationError(msg)

        try:
            blueprint = PipelineBlueprint.objects.get(
                name=blueprint_name,
                is_active=True,
            )
        except ObjectDoesNotExist as exc:
            msg = f'Blueprint not found: {blueprint_name}'
            raise ValidationError(msg) from exc

        run = PipelineRun.objects.create(
            channel=channel,
            blueprint=blueprint,
            blueprint_snapshot=blueprint.graph,
            topic=payload.topic,
            status=RunStatus.PENDING,
            source_idea_id=(
                uuid.UUID(payload.source_idea_id)
                if payload.source_idea_id
                else None
            ),
        )
        return str(run.id)

    @staticmethod
    async def _kick_advance(run_id: str) -> None:
        from server.apps.pipelines.tasks import (
            advance_pipeline,
        )

        await advance_pipeline.kiq(run_id)
