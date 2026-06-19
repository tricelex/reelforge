"""Business logic for topic ideation."""

import uuid
from typing import TYPE_CHECKING, Any, final

import attrs
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction

from server.apps.ideas.ideation import run_ideation_agent
from server.apps.ideas.logic.constants import IdeaStatus
from server.apps.ideas.logic.filters import filter_ideation_candidates
from server.apps.ideas.logic.schemas import SourceSnapshot, TopicCandidate
from server.apps.ideas.logic.value_objects import (
    IdeaGeneratePayload,
    IdeaListPayload,
    PromoteIdeaResultPayload,
    TopicIdeaPatchPayload,
    TopicIdeaPayload,
)
from server.apps.ideas.selectors import (
    _idea_to_payload,
    build_ideation_context,
    get_idea,
    list_ideas,
)
from server.apps.ideas.source_ingest import ingest_youtube
from server.apps.pipelines.logic.value_objects import RunCreatePayload
from server.apps.pipelines.services.pipeline_run import PipelineRunService

if TYPE_CHECKING:
    from server.apps.channels.models import NicheConfig
    from server.apps.ideas.models import TopicIdea

_MAX_GENERATE = 20
_MIN_GENERATE = 1


def _candidate_metadata(
    candidate: TopicCandidate,
    *,
    source: SourceSnapshot | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        'source_type': 'youtube_remix' if source else 'niche_only',
        'remix_strategy': candidate.remix_strategy,
        'hook_pattern': candidate.hook_pattern,
        'differentiation': candidate.differentiation,
        'source_refs': [
            ref.model_dump() for ref in candidate.source_refs
        ],
    }
    if source is not None:
        metadata['source_snapshot'] = {
            'url': source.url,
            'video_id': source.video_id,
            'title': source.title,
            'channel': source.channel,
            'view_count': source.view_count,
        }
    return metadata


def _candidates_to_rows(
    candidates: list[TopicCandidate],
    *,
    niche: 'NicheConfig',
    source: SourceSnapshot | None,
) -> list[dict[str, Any]]:
    return [
        {
            'channel_id': niche.channel_id,
            'niche_id': niche.id,
            'title': candidate.title[:200],
            'topic': candidate.topic,
            'score': candidate.score,
            'metadata': _candidate_metadata(candidate, source=source),
        }
        for candidate in candidates
    ]


def _apply_idea_patch(
    idea: 'TopicIdea',
    payload: TopicIdeaPatchPayload,
) -> list[str]:
    update_fields: list[str] = []
    if payload.title is not None:
        idea.title = payload.title
        update_fields.append('title')
    if payload.topic is not None:
        idea.topic = payload.topic
        update_fields.append('topic')
    if payload.score is not None:
        idea.score = payload.score
        update_fields.append('score')
    if payload.rejection_reason is not None:
        idea.rejection_reason = payload.rejection_reason
        update_fields.append('rejection_reason')
    return update_fields


@final
@attrs.define(slots=True, frozen=True)
class IdeationService:
    """Generate, curate, and promote topic backlog items."""

    _runs: PipelineRunService

    def generate(
        self,
        niche_id: str,
        payload: IdeaGeneratePayload,
    ) -> IdeaListPayload:
        """Create a batch of backlog ideas for one niche."""
        from server.apps.channels.models import (  # noqa: PLC0415
            ChannelKind,
            NicheConfig,
        )
        from server.apps.ideas.models import TopicIdea  # noqa: PLC0415

        count = payload.count
        if not (_MIN_GENERATE <= count <= _MAX_GENERATE):
            msg = f'count must be between {_MIN_GENERATE} and {_MAX_GENERATE}'
            raise ValidationError(msg)

        try:
            niche = NicheConfig.objects.select_related(
                'channel',
                'format',
            ).get(
                id=uuid.UUID(niche_id),
            )
        except ObjectDoesNotExist as exc:
            msg = f'Niche not found: {niche_id}'
            raise ValidationError(msg) from exc

        if niche.channel.kind != ChannelKind.LONGFORM:
            msg = 'Ideation is only supported for longform channels'
            raise ValidationError(msg)

        context = build_ideation_context(niche)
        source = (
            ingest_youtube(payload.source_url)
            if payload.source_url
            else None
        )
        output = run_ideation_agent(
            context,
            source=source,
            count=count,
        )
        filtered = filter_ideation_candidates(
            output.ideas,
            count=count,
            existing=context.existing_topics,
            banned_topics=context.banned_topics,
        )
        rows = _candidates_to_rows(filtered, niche=niche, source=source)
        if not rows:
            msg = 'No unique ideas could be generated'
            raise ValidationError(msg)

        created = TopicIdea.objects.bulk_create(
            [
                TopicIdea(
                    channel_id=row['channel_id'],
                    niche_id=row['niche_id'],
                    title=str(row['title']),
                    topic=str(row['topic']),
                    score=float(row['score']),
                    metadata=dict(row['metadata']),
                    status=IdeaStatus.BACKLOG,
                )
                for row in rows
            ],
        )
        return IdeaListPayload(
            items=[_idea_to_payload(row) for row in created],
            next_cursor=None,
            total=len(created),
        )

    def patch(
        self,
        idea_id: str,
        payload: TopicIdeaPatchPayload,
    ) -> TopicIdeaPayload:
        """Update backlog fields on one idea."""
        from server.apps.ideas.models import TopicIdea  # noqa: PLC0415

        idea = TopicIdea.objects.get(id=uuid.UUID(idea_id))
        if idea.status == IdeaStatus.PROMOTED:
            msg = 'Promoted ideas cannot be edited'
            raise ValidationError(msg)

        update_fields = _apply_idea_patch(idea, payload)
        if payload.status is not None:
            if payload.status not in IdeaStatus.values:
                msg = f'Invalid status: {payload.status}'
                raise ValidationError(msg)
            idea.status = payload.status
            update_fields.append('status')
        if update_fields:
            idea.save(update_fields=update_fields)
        return get_idea(idea_id)

    def promote(self, idea_id: str) -> PromoteIdeaResultPayload:
        """Promote a backlog idea into a new longform pipeline run."""
        from server.apps.ideas.models import TopicIdea  # noqa: PLC0415

        with transaction.atomic():
            idea = (
                TopicIdea.objects
                .select_for_update()
                .select_related('channel')
                .get(id=uuid.UUID(idea_id))
            )
            if idea.status not in {IdeaStatus.BACKLOG, IdeaStatus.APPROVED}:
                msg = f'Idea cannot be promoted from status {idea.status}'
                raise ValidationError(msg)

            run_detail = self._runs.create(
                RunCreatePayload(
                    channel_id=str(idea.channel_id),
                    topic=idea.topic,
                    source_idea_id=str(idea.id),
                ),
            )
            idea.status = IdeaStatus.PROMOTED
            idea.run_id = uuid.UUID(run_detail.id)
            idea.save(update_fields=['status', 'run'])

        return PromoteIdeaResultPayload(
            idea_id=str(idea.id),
            run_id=run_detail.id,
            status=IdeaStatus.PROMOTED,
        )

    def list_backlog(
        self,
        *,
        status: str | None,
        channel_id: str | None,
        cursor: str | None,
        limit: int,
    ) -> IdeaListPayload:
        """Return paginated backlog rows."""
        return list_ideas(
            status=status,
            channel_id=channel_id,
            cursor=cursor,
            limit=limit,
        )
