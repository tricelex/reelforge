"""Tests for ideation DMR API."""

import uuid
from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    NicheConfig,
    PublishMode,
)
from server.apps.ideas.logic.constants import IdeaStatus
from server.apps.ideas.logic.schemas import IdeationOutput, TopicCandidate
from server.apps.ideas.models import TopicIdea
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    RunStatus,
)


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    """Create a longform channel with niche config."""
    return Channel.objects.create(
        name='Ideation Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def niche(channel: Channel) -> NicheConfig:
    """Create niche config for ideation tests."""
    return NicheConfig.objects.create(
        channel=channel,
        audience='history buffs',
        angle='ancient empires',
    )


@pytest.fixture
def blueprint(db) -> PipelineBlueprint:  # type: ignore[no-untyped-def]
    """Active longform blueprint."""
    return PipelineBlueprint.objects.create(
        name='longform_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'research', 'depends_on': []}]},
        is_active=True,
    )


@pytest.fixture
def idea(channel: Channel, niche: NicheConfig) -> TopicIdea:
    """Seed backlog idea."""
    return TopicIdea.objects.create(
        channel=channel,
        niche=niche,
        title='Fall of Rome',
        topic='Why Rome collapsed in the 5th century',
        score=0.9,
        status=IdeaStatus.BACKLOG,
    )


@pytest.mark.django_db(transaction=True)
def test_generate_ideas(
    dmr_client: DMRClient,
    niche: NicheConfig,
    auth_headers: dict[str, str],
) -> None:
    """POST generate creates backlog rows for a niche."""
    candidates = [
        TopicCandidate(
            title=f'Idea {index}',
            topic=f'Unique topic seed {index}',
            score=0.9 - (index * 0.1),
            remix_strategy='deeper_dive',
            hook_pattern='cold_open',
            differentiation=f'Angle {index}',
        )
        for index in range(3)
    ]
    with patch(
        'server.apps.ideas.services.run_ideation_agent',
        return_value=IdeationOutput(ideas=candidates),
    ):
        response = dmr_client.post(
            reverse(
                'api:ideas_api:niche-ideas-generate',
                kwargs={'niche_id': niche.id},
            ),
            data={'count': 3},
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body['total'] == 3
    assert len(body['items']) == 3
    assert body['items'][0]['metadata']['source_type'] == 'niche_only'
    assert TopicIdea.objects.filter(niche=niche).count() == 3


@pytest.mark.django_db(transaction=True)
def test_get_idea_detail(
    dmr_client: DMRClient,
    idea: TopicIdea,
    auth_headers: dict[str, str],
) -> None:
    """GET idea detail returns one backlog row."""
    response = dmr_client.get(
        reverse(
            'api:ideas_api:idea-detail',
            kwargs={'idea_id': idea.id},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['id'] == str(idea.id)


@pytest.mark.django_db(transaction=True)
def test_list_and_patch_idea(
    dmr_client: DMRClient,
    idea: TopicIdea,
    auth_headers: dict[str, str],
) -> None:
    """GET ideas and PATCH one backlog row."""
    list_resp = dmr_client.get(
        reverse('api:ideas_api:idea-collection'),
        query_params={'status': IdeaStatus.BACKLOG},
        headers=auth_headers,
    )
    assert list_resp.status_code == HTTPStatus.OK
    assert list_resp.json()['total'] == 1

    patch_resp = dmr_client.patch(
        reverse(
            'api:ideas_api:idea-detail',
            kwargs={'idea_id': idea.id},
        ),
        data={'status': IdeaStatus.APPROVED, 'score': 0.95},
        headers=auth_headers,
    )
    assert patch_resp.status_code == HTTPStatus.OK
    assert patch_resp.json()['status'] == IdeaStatus.APPROVED


@pytest.mark.django_db(transaction=True)
def test_promote_idea_creates_run(
    dmr_client: DMRClient,
    idea: TopicIdea,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    """POST promote creates a pipeline run linked to the idea."""
    with patch('server.apps.pipelines.services.pipeline_run.kiq_task'):
        response = dmr_client.post(
            reverse(
                'api:ideas_api:idea-promote',
                kwargs={'idea_id': idea.id},
            ),
            headers=auth_headers,
        )

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['status'] == IdeaStatus.PROMOTED

    idea.refresh_from_db()
    assert idea.status == IdeaStatus.PROMOTED
    assert idea.run_id is not None

    run = PipelineRun.objects.get(id=idea.run_id)
    assert run.topic == idea.topic
    assert str(run.source_idea_id) == str(idea.id)
    assert run.status == RunStatus.PENDING


@pytest.mark.django_db(transaction=True)
def test_get_idea_not_found(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET idea detail returns 404 for an unknown id."""
    response = dmr_client.get(
        reverse(
            'api:ideas_api:idea-detail',
            kwargs={'idea_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db(transaction=True)
def test_patch_promoted_idea_returns_422(
    dmr_client: DMRClient,
    channel: Channel,
    niche: NicheConfig,
    auth_headers: dict[str, str],
) -> None:
    """PATCH on a promoted idea returns 422."""
    promoted = TopicIdea.objects.create(
        channel=channel,
        niche=niche,
        title='Done',
        topic='Already promoted',
        status=IdeaStatus.PROMOTED,
    )

    response = dmr_client.patch(
        reverse(
            'api:ideas_api:idea-detail',
            kwargs={'idea_id': promoted.id},
        ),
        data={'title': 'Nope'},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_generate_invalid_count_returns_422(
    dmr_client: DMRClient,
    niche: NicheConfig,
    auth_headers: dict[str, str],
) -> None:
    """POST generate with invalid count returns 422."""
    response = dmr_client.post(
        reverse(
            'api:ideas_api:niche-ideas-generate',
            kwargs={'niche_id': niche.id},
        ),
        data={'count': 0},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_promote_idea_not_found(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST promote returns 404 for an unknown idea."""
    response = dmr_client.post(
        reverse(
            'api:ideas_api:idea-promote',
            kwargs={'idea_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db(transaction=True)
def test_list_ideas_channel_filter_and_cursor(
    dmr_client: DMRClient,
    channel: Channel,
    niche: NicheConfig,
    auth_headers: dict[str, str],
) -> None:
    """GET ideas supports channel_id filter and cursor pagination."""
    for index in range(3):
        TopicIdea.objects.create(
            channel=channel,
            niche=niche,
            title=f'Cursor idea {index}',
            topic=f'Topic {index}',
            status=IdeaStatus.BACKLOG,
        )

    first = dmr_client.get(
        (
            f'{reverse("api:ideas_api:idea-collection")}'
            f'?channel_id={channel.id}'
            f'&status={IdeaStatus.BACKLOG}'
            '&limit=2'
        ),
        headers=auth_headers,
    )
    assert first.status_code == HTTPStatus.OK
    body = first.json()
    assert body['total'] == 3
    assert len(body['items']) == 2
    assert body['next_cursor'] is not None

    second = dmr_client.get(
        (
            f'{reverse("api:ideas_api:idea-collection")}'
            f'?channel_id={channel.id}'
            f'&status={IdeaStatus.BACKLOG}'
            '&limit=2'
            f'&cursor={body["next_cursor"]}'
        ),
        headers=auth_headers,
    )
    assert second.status_code == HTTPStatus.OK
    assert len(second.json()['items']) == 1


@pytest.mark.django_db(transaction=True)
def test_list_ideas_invalid_limit_defaults(
    dmr_client: DMRClient,
    idea: TopicIdea,
    auth_headers: dict[str, str],
) -> None:
    """GET ideas ignores non-integer limit values."""
    response = dmr_client.get(
        reverse('api:ideas_api:idea-collection'),
        query_params={
            'status': IdeaStatus.BACKLOG,
            'limit': 'not-a-number',
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['total'] == 1


@pytest.mark.django_db(transaction=True)
def test_patch_idea_validation_error_returns_422(
    dmr_client: DMRClient,
    idea: TopicIdea,
    auth_headers: dict[str, str],
) -> None:
    """PATCH validation errors return 422."""
    response = dmr_client.patch(
        reverse(
            'api:ideas_api:idea-detail',
            kwargs={'idea_id': idea.id},
        ),
        data={'status': 'INVALID'},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_generate_validation_error_returns_422(
    dmr_client: DMRClient,
    niche: NicheConfig,
    auth_headers: dict[str, str],
) -> None:
    """POST generate validation errors return 422."""
    response = dmr_client.post(
        reverse(
            'api:ideas_api:niche-ideas-generate',
            kwargs={'niche_id': niche.id},
        ),
        data={'count': 99},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db(transaction=True)
def test_promote_validation_error_returns_422(
    dmr_client: DMRClient,
    channel: Channel,
    niche: NicheConfig,
    auth_headers: dict[str, str],
) -> None:
    """POST promote validation errors return 422."""
    rejected = TopicIdea.objects.create(
        channel=channel,
        niche=niche,
        title='Rejected',
        topic='No promote',
        status=IdeaStatus.REJECTED,
    )
    response = dmr_client.post(
        reverse(
            'api:ideas_api:idea-promote',
            kwargs={'idea_id': rejected.id},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_manual_create_idea(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """POST /api/ideas/ creates a manual backlog row."""
    response = dmr_client.post(
        reverse('api:ideas_api:idea-collection'),
        data={
            'channel_id': str(channel.id),
            'title': 'Manual Topic',
            'topic': 'A manually entered video idea',
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body['title'] == 'Manual Topic'
    assert body['status'] == IdeaStatus.BACKLOG


@pytest.mark.django_db
def test_generate_ideas_by_channel(
    dmr_client: DMRClient,
    niche: NicheConfig,
    auth_headers: dict[str, str],
) -> None:
    """POST channel ideas generate resolves niche from channel_id."""
    candidates = [
        TopicCandidate(
            title='Channel Route Idea',
            topic='Generated via channel route',
            score=0.88,
            remix_strategy='',
            hook_pattern='',
            differentiation='',
            source_refs=[],
        ),
    ]
    with patch(
        'server.apps.ideas.services.run_ideation_agent',
        return_value=IdeationOutput(ideas=candidates),
    ):
        response = dmr_client.post(
            reverse(
                'api:ideas_api:channel-ideas-generate',
                kwargs={'channel_id': niche.channel_id},
            ),
            data={'count': 1},
            headers=auth_headers,
        )
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['total'] == 1


@pytest.mark.django_db
def test_manual_create_idea_with_niche(
    dmr_client: DMRClient,
    channel: Channel,
    niche: NicheConfig,
    auth_headers: dict[str, str],
) -> None:
    """POST /api/ideas/ accepts optional niche_id."""
    response = dmr_client.post(
        reverse('api:ideas_api:idea-collection'),
        data={
            'channel_id': str(channel.id),
            'niche_id': str(niche.id),
            'title': 'Niche Manual',
            'topic': 'Scoped to niche',
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()['niche_id'] == str(niche.id)


@pytest.mark.django_db
def test_manual_create_idea_unknown_channel(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST /api/ideas/ rejects unknown channel."""
    response = dmr_client.post(
        reverse('api:ideas_api:idea-collection'),
        data={
            'channel_id': str(uuid.uuid4()),
            'title': 'Bad',
            'topic': 'Bad topic',
        },
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_generate_ideas_by_channel_unknown(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST channel ideas generate rejects unknown channel."""
    response = dmr_client.post(
        reverse(
            'api:ideas_api:channel-ideas-generate',
            kwargs={'channel_id': uuid.uuid4()},
        ),
        data={'count': 1},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_generate_ideas_by_channel_without_niche(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """POST channel ideas generate rejects channels without a niche."""
    channel = Channel.objects.create(
        name='No Niche Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )
    response = dmr_client.post(
        reverse(
            'api:ideas_api:channel-ideas-generate',
            kwargs={'channel_id': channel.id},
        ),
        data={'count': 1},
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_list_ideas_filter_by_niche(
    dmr_client: DMRClient,
    niche: NicheConfig,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/ideas/ accepts niche_id filter."""
    TopicIdea.objects.create(
        niche=niche,
        channel_id=niche.channel_id,
        title='Niche Filtered',
        topic='Only this niche',
    )
    response = dmr_client.get(
        reverse('api:ideas_api:idea-collection')
        + f'?niche_id={niche.id}',
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()['total'] == 1
