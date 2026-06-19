"""Tests for IdeationService."""

from unittest.mock import AsyncMock, patch

import pytest
from django.core.exceptions import ValidationError

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    NicheConfig,
    PublishMode,
)
from server.apps.ideas.logic.constants import IdeaStatus
from server.apps.ideas.logic.schemas import IdeationOutput, TopicCandidate
from server.apps.ideas.logic.value_objects import (
    IdeaGeneratePayload,
    TopicIdeaPatchPayload,
)
from server.apps.ideas.models import TopicIdea
from server.apps.ideas.services import IdeationService
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
)
from server.common import container as container_module


@pytest.fixture
def longform_channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Longform channel for ideation service tests."""
    return Channel.objects.create(
        name='Longform Ideas',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def clipping_channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Clipping channel (ideation not supported)."""
    return Channel.objects.create(
        name='Clipping Ideas',
        kind=ChannelKind.CLIPPING,
    )


@pytest.fixture
def niche(longform_channel: Channel) -> NicheConfig:
    """Niche config on a longform channel."""
    return NicheConfig.objects.create(
        channel=longform_channel,
        audience='history buffs',
        angle='ancient empires',
    )


@pytest.fixture
def clipping_niche(clipping_channel: Channel) -> NicheConfig:
    """Niche on a clipping channel."""
    return NicheConfig.objects.create(
        channel=clipping_channel,
        audience='clip fans',
        angle='podcast highlights',
    )


@pytest.fixture
def ideation_service() -> IdeationService:
    """Resolve IdeationService from the DI container."""
    return container_module.container.resolve(IdeationService)


@pytest.mark.django_db
def test_generate_invalid_count(
    ideation_service: IdeationService,
    niche: NicheConfig,
) -> None:
    """Generate rejects counts outside the allowed range."""
    with pytest.raises(ValidationError, match='count must be between'):
        ideation_service.generate(
            str(niche.id),
            IdeaGeneratePayload(count=0),
        )
    with pytest.raises(ValidationError, match='count must be between'):
        ideation_service.generate(
            str(niche.id),
            IdeaGeneratePayload(count=21),
        )


@pytest.mark.django_db
def test_generate_missing_niche(ideation_service: IdeationService) -> None:
    """Generate raises when the niche does not exist."""
    missing_id = '00000000-0000-0000-0000-000000000001'
    with pytest.raises(ValidationError, match='Niche not found'):
        ideation_service.generate(
            missing_id,
            IdeaGeneratePayload(count=3),
        )


@pytest.mark.django_db
def test_generate_clipping_channel_rejected(
    ideation_service: IdeationService,
    clipping_niche: NicheConfig,
) -> None:
    """Generate rejects clipping channels."""
    with pytest.raises(ValidationError, match='longform channels'):
        ideation_service.generate(
            str(clipping_niche.id),
            IdeaGeneratePayload(count=3),
        )


@pytest.mark.django_db
def test_generate_skips_existing_topics(
    ideation_service: IdeationService,
    niche: NicheConfig,
    longform_channel: Channel,
) -> None:
    """Generate avoids topics already present on the channel."""
    existing_topic = 'How Roman logistics caused collapse'
    TopicIdea.objects.create(
        channel=longform_channel,
        niche=niche,
        title='Existing',
        topic=existing_topic,
        status=IdeaStatus.BACKLOG,
    )
    mock_output = IdeationOutput(
        ideas=[
            TopicCandidate(
                title='Dup',
                topic=existing_topic,
                score=0.99,
                remix_strategy='a',
                hook_pattern='h1',
                differentiation='d1',
            ),
            TopicCandidate(
                title='Fresh',
                topic='Unique grain route angle',
                score=0.8,
                remix_strategy='b',
                hook_pattern='h2',
                differentiation='d2',
            ),
        ],
    )

    with patch(
        'server.apps.ideas.services.run_ideation_agent',
        return_value=mock_output,
    ):
        result = ideation_service.generate(
            str(niche.id),
            IdeaGeneratePayload(count=1),
        )

    assert result.total == 1
    assert result.items[0].topic == 'Unique grain route angle'


@pytest.mark.django_db
def test_patch_no_field_changes_skips_save(
    ideation_service: IdeationService,
    niche: NicheConfig,
    longform_channel: Channel,
) -> None:
    """Patch with no effective changes does not write to the database."""
    idea = TopicIdea.objects.create(
        channel=longform_channel,
        niche=niche,
        title='No changes',
        topic='Topic',
        status=IdeaStatus.BACKLOG,
    )

    updated = ideation_service.patch(
        str(idea.id),
        TopicIdeaPatchPayload(),
    )
    assert updated.title == 'No changes'


@pytest.mark.django_db
def test_patch_status_only(
    ideation_service: IdeationService,
    niche: NicheConfig,
    longform_channel: Channel,
) -> None:
    """Patch can update status without touching other fields."""
    idea = TopicIdea.objects.create(
        channel=longform_channel,
        niche=niche,
        title='Status only',
        topic='Topic',
        status=IdeaStatus.BACKLOG,
    )

    updated = ideation_service.patch(
        str(idea.id),
        TopicIdeaPatchPayload(status=IdeaStatus.APPROVED),
    )
    assert updated.status == IdeaStatus.APPROVED


@pytest.mark.django_db
def test_patch_title_topic_score_rejection_reason(
    ideation_service: IdeationService,
    niche: NicheConfig,
    longform_channel: Channel,
) -> None:
    """Patch updates editable backlog fields."""
    idea = TopicIdea.objects.create(
        channel=longform_channel,
        niche=niche,
        title='Old title',
        topic='Old topic',
        score=0.5,
        status=IdeaStatus.BACKLOG,
    )

    updated = ideation_service.patch(
        str(idea.id),
        TopicIdeaPatchPayload(
            title='New title',
            topic='New topic',
            score=0.99,
            rejection_reason='Needs work',
        ),
    )

    assert updated.title == 'New title'
    assert updated.topic == 'New topic'
    assert updated.score == 0.99
    assert updated.rejection_reason == 'Needs work'


@pytest.mark.django_db
def test_patch_promoted_idea_rejected(
    ideation_service: IdeationService,
    niche: NicheConfig,
    longform_channel: Channel,
) -> None:
    """Promoted ideas cannot be edited."""
    idea = TopicIdea.objects.create(
        channel=longform_channel,
        niche=niche,
        title='Promoted',
        topic='Already promoted',
        status=IdeaStatus.PROMOTED,
    )

    with pytest.raises(ValidationError, match='cannot be edited'):
        ideation_service.patch(
            str(idea.id),
            TopicIdeaPatchPayload(title='Nope'),
        )


@pytest.mark.django_db
def test_patch_invalid_status(
    ideation_service: IdeationService,
    niche: NicheConfig,
    longform_channel: Channel,
) -> None:
    """Patch rejects unknown status values."""
    idea = TopicIdea.objects.create(
        channel=longform_channel,
        niche=niche,
        title='Status test',
        topic='Topic',
        status=IdeaStatus.BACKLOG,
    )

    with pytest.raises(ValidationError, match='Invalid status'):
        ideation_service.patch(
            str(idea.id),
            TopicIdeaPatchPayload(status='INVALID'),
        )


@pytest.mark.django_db
def test_promote_wrong_status(
    ideation_service: IdeationService,
    niche: NicheConfig,
    longform_channel: Channel,
) -> None:
    """Promote rejects ideas not in backlog or approved."""
    idea = TopicIdea.objects.create(
        channel=longform_channel,
        niche=niche,
        title='Rejected',
        topic='Cannot promote',
        status=IdeaStatus.REJECTED,
    )

    with pytest.raises(ValidationError, match='cannot be promoted'):
        ideation_service.promote(str(idea.id))


@pytest.mark.django_db
def test_list_backlog_channel_filter_and_cursor(
    ideation_service: IdeationService,
    niche: NicheConfig,
    longform_channel: Channel,
) -> None:
    """list_backlog filters by channel and paginates with cursors."""
    other_channel = Channel.objects.create(
        name='Other',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )
    for index in range(3):
        TopicIdea.objects.create(
            channel=longform_channel,
            niche=niche,
            title=f'Idea {index}',
            topic=f'Topic {index}',
            status=IdeaStatus.BACKLOG,
        )
    TopicIdea.objects.create(
        channel=other_channel,
        niche=niche,
        title='Other channel',
        topic='Other topic',
        status=IdeaStatus.BACKLOG,
    )

    first_page = ideation_service.list_backlog(
        status=IdeaStatus.BACKLOG,
        channel_id=str(longform_channel.id),
        cursor=None,
        limit=2,
    )
    assert first_page.total == 3
    assert len(first_page.items) == 2
    assert first_page.next_cursor is not None

    second_page = ideation_service.list_backlog(
        status=IdeaStatus.BACKLOG,
        channel_id=str(longform_channel.id),
        cursor=first_page.next_cursor,
        limit=2,
    )
    assert len(second_page.items) == 1
    assert second_page.next_cursor is None


@pytest.mark.django_db
def test_list_backlog_channel_filter_without_status(
    ideation_service: IdeationService,
    niche: NicheConfig,
    longform_channel: Channel,
) -> None:
    """list_backlog can filter by channel without a status."""
    TopicIdea.objects.create(
        channel=longform_channel,
        niche=niche,
        title='Channel only',
        topic='Topic',
        status=IdeaStatus.BACKLOG,
    )

    result = ideation_service.list_backlog(
        status=None,
        channel_id=str(longform_channel.id),
        cursor=None,
        limit=10,
    )
    assert result.total == 1


@pytest.mark.django_db(transaction=True)
def test_promote_from_backlog(
    ideation_service: IdeationService,
    niche: NicheConfig,
    longform_channel: Channel,
) -> None:
    """Promote accepts backlog ideas."""
    PipelineBlueprint.objects.filter(name='longform_v1').update(is_active=False)
    PipelineBlueprint.objects.update_or_create(
        name='longform_v1',
        defaults={
            'kind': PipelineKind.LONGFORM,
            'graph': {'stages': [{'key': 'research', 'depends_on': []}]},
            'is_active': True,
        },
    )
    idea = TopicIdea.objects.create(
        channel=longform_channel,
        niche=niche,
        title='Backlog promote',
        topic='Backlog topic',
        status=IdeaStatus.BACKLOG,
    )

    with patch(
        'server.apps.pipelines.tasks.advance_pipeline.kiq',
        new_callable=AsyncMock,
    ):
        result = ideation_service.promote(str(idea.id))

    assert result.status == IdeaStatus.PROMOTED


@pytest.mark.django_db(transaction=True)
def test_promote_success(
    ideation_service: IdeationService,
    niche: NicheConfig,
    longform_channel: Channel,
) -> None:
    """Promote creates a pipeline run from an approved idea."""
    PipelineBlueprint.objects.filter(name='longform_v1').update(is_active=False)
    PipelineBlueprint.objects.update_or_create(
        name='longform_v1',
        defaults={
            'kind': PipelineKind.LONGFORM,
            'graph': {'stages': [{'key': 'research', 'depends_on': []}]},
            'is_active': True,
        },
    )
    idea = TopicIdea.objects.create(
        channel=longform_channel,
        niche=niche,
        title='Promote me',
        topic='Worthy topic',
        status=IdeaStatus.APPROVED,
    )

    with patch(
        'server.apps.pipelines.tasks.advance_pipeline.kiq',
        new_callable=AsyncMock,
    ):
        result = ideation_service.promote(str(idea.id))

    assert result.status == IdeaStatus.PROMOTED
    idea.refresh_from_db()
    assert idea.run_id is not None
    assert PipelineRun.objects.filter(id=idea.run_id).exists()
