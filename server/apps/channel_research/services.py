"""Business logic for channel research jobs."""

import uuid
from typing import final

import attrs
import msgspec
import pydantic
from django.core.exceptions import ValidationError

from server.apps.channel_research.logic.constants import (
    ChannelResearchKind,
    ChannelResearchStatus,
    DeepAnalysisStatus,
)
from server.apps.channel_research.logic.schemas import (
    ChannelSpecModel,
    validate_channel_spec,
    validate_medium_lock,
)
from server.apps.channel_research.logic.value_objects import (
    ChannelResearchCreatePayload,
    ChannelResearchJobPayload,
    ChannelResearchListPayload,
    ChannelResearchSpecPatchPayload,
    ChannelSpecPayload,
    ChannelSpecSeedIdeaPayload,
    ChannelSpecValidateResultPayload,
)
from server.apps.channel_research.models import ChannelResearchJob
from server.apps.channel_research.selectors import (
    get_job,
    job_to_payload,
    list_jobs,
)
from server.common.taskiq_sender import kiq_task

_YOUTUBE_HINTS = ('youtube.com', 'youtu.be')
_EDITABLE_STATUSES = frozenset({ChannelResearchStatus.SUCCEEDED})
_RETRYABLE_STATUSES = frozenset({
    ChannelResearchStatus.FAILED,
    ChannelResearchStatus.SUCCEEDED,
})
_DEEP_ANALYSIS_APPLICABLE_STATUSES = frozenset({
    DeepAnalysisStatus.SUCCEEDED,
})
_MAX_MERGED_SEED_IDEAS = 12


def _validate_source_channel_id(job: ChannelResearchJob) -> str:
    if not job.source_channel_id:
        msg = 'source_channel_id is required before Deep Analysis can run'
        raise ValidationError(msg)
    return job.source_channel_id


def _validate_source_url(url: str) -> str:
    stripped = url.strip()
    if not stripped:
        msg = 'source_channel_url is required'
        raise ValidationError(msg)
    lowered = stripped.lower()
    if not any(hint in lowered for hint in _YOUTUBE_HINTS):
        msg = 'source_channel_url must be a YouTube channel URL'
        raise ValidationError(msg)
    return stripped


def _validate_kind(kind: str) -> str:
    if kind not in ChannelResearchKind.values:
        msg = f'Invalid kind: {kind}'
        raise ValidationError(msg)
    return kind


def _enqueue(job: ChannelResearchJob) -> None:
    from server.apps.channel_research.tasks import (  # noqa: PLC0415
        run_channel_research_task,
    )

    kiq_task(run_channel_research_task, str(job.id))
    job.status = ChannelResearchStatus.QUEUED
    job.save(update_fields=['status', 'updated_at'])


def _reset_outputs(job: ChannelResearchJob) -> None:
    job.research_report = {}
    job.channel_spec = {}
    job.tool_trace = []
    job.usage = {}
    job.error_message = ''
    job.source_channel_id = ''
    job.source_channel_name = ''
    job.status = ChannelResearchStatus.PENDING


def _spec_model(payload: ChannelSpecPayload) -> ChannelSpecModel:
    return ChannelSpecModel.model_validate(msgspec.to_builtins(payload))


def _flatten_pydantic_errors(exc: pydantic.ValidationError) -> list[str]:
    errors: list[str] = []
    max_errors = 20
    for index, item in enumerate(exc.errors()):
        if index >= max_errors:
            break
        location = '.'.join(str(part) for part in item.get('loc', ()))
        message = str(item.get('msg', 'invalid'))
        errors.append(f'{location}: {message}' if location else message)
    return errors or [str(exc)]


def _collect_spec_errors(
    payload: ChannelSpecPayload,
) -> list[str]:
    try:
        spec = _spec_model(payload)
    except pydantic.ValidationError as exc:
        return _flatten_pydantic_errors(exc)
    try:
        validate_channel_spec(spec)
        validate_medium_lock(spec)
    except ValueError as exc:
        return [str(exc)]
    return []


@final
@attrs.define(slots=True, frozen=True)
class ChannelResearchService:
    """Create, patch, retry, and list channel research jobs."""

    def create(
        self,
        payload: ChannelResearchCreatePayload,
        *,
        created_by_id: int | None,
    ) -> ChannelResearchJobPayload:
        """Persist a job and enqueue the research agent."""
        url = _validate_source_url(payload.source_channel_url)
        kind = _validate_kind(payload.kind)
        job = ChannelResearchJob.objects.create(
            source_channel_url=url,
            target_market=payload.target_market.strip(),
            working_name=payload.working_name.strip()[:120],
            kind=kind,
            notes=payload.notes.strip(),
            status=ChannelResearchStatus.PENDING,
            created_by_id=created_by_id,
        )
        _enqueue(job)
        return job_to_payload(job)

    def get(self, job_id: str) -> ChannelResearchJobPayload:
        """Return one job."""
        return get_job(job_id)

    def list_jobs(
        self,
        *,
        status: str | None,
        cursor: str | None,
        limit: int,
    ) -> ChannelResearchListPayload:
        """Return paginated jobs."""
        return list_jobs(status=status, cursor=cursor, limit=limit)

    def patch_spec(
        self,
        job_id: str,
        payload: ChannelResearchSpecPatchPayload,
    ) -> ChannelResearchJobPayload:
        """Replace channel_spec when the job has succeeded."""
        job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
        if job.status not in _EDITABLE_STATUSES:
            msg = 'channel_spec can only be edited when status is SUCCEEDED'
            raise ValidationError(msg)
        errors = _collect_spec_errors(payload.channel_spec)
        if errors:
            raise ValidationError(errors)
        job.channel_spec = msgspec.to_builtins(payload.channel_spec)
        job.save(update_fields=['channel_spec', 'updated_at'])
        return job_to_payload(job)

    def validate_spec(
        self,
        payload: ChannelSpecPayload,
    ) -> ChannelSpecValidateResultPayload:
        """Return quality-bar errors for a ChannelSpec JSON body."""
        errors = _collect_spec_errors(payload)
        return ChannelSpecValidateResultPayload(
            ok=not errors,
            errors=errors,
        )

    def retry(self, job_id: str) -> ChannelResearchJobPayload:
        """Reset a failed or succeeded job and re-enqueue."""
        job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
        if job.status not in _RETRYABLE_STATUSES:
            msg = (
                'Only FAILED or SUCCEEDED jobs can be retried '
                f'(status={job.status})'
            )
            raise ValidationError(msg)
        _reset_outputs(job)
        job.save()
        _enqueue(job)
        return job_to_payload(job)

    def trigger_deep_analysis(self, job_id: str) -> ChannelResearchJobPayload:
        """Kick off NexLev's async Deep Analysis job for this channel."""
        job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
        _validate_source_channel_id(job)
        job.deep_analysis_status = DeepAnalysisStatus.RUNNING
        job.deep_analysis_error_message = ''
        job.save(
            update_fields=[
                'deep_analysis_status',
                'deep_analysis_error_message',
                'updated_at',
            ],
        )
        from server.apps.channel_research.tasks import (  # noqa: PLC0415
            run_deep_analysis_task,
        )

        kiq_task(run_deep_analysis_task, str(job.id))
        return job_to_payload(job)

    def apply_suggested_topics(
        self,
        job_id: str,
    ) -> ChannelResearchJobPayload:
        """Merge NexLev's suggested_topics into channel_spec.seed_ideas."""
        job = ChannelResearchJob.objects.get(id=uuid.UUID(job_id))
        if job.deep_analysis_status not in _DEEP_ANALYSIS_APPLICABLE_STATUSES:
            msg = (
                'deep_analysis must be SUCCEEDED before applying suggested'
                ' topics'
            )
            raise ValidationError(msg)
        result = job.deep_analysis_result or {}
        topics = result.get('suggested_topics', [])
        existing = list(job.channel_spec.get('seed_ideas', []))
        new_ideas = [
            msgspec.to_builtins(
                ChannelSpecSeedIdeaPayload(
                    title=topic['title'][:200],
                    topic=topic.get('description', ''),
                ),
            )
            for topic in topics
        ]
        merged = (existing + new_ideas)[:_MAX_MERGED_SEED_IDEAS]
        job.channel_spec = {**job.channel_spec, 'seed_ideas': merged}
        job.save(update_fields=['channel_spec', 'updated_at'])
        return job_to_payload(job)
