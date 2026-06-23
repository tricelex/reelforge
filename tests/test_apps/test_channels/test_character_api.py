"""Tests for character studio and niche APIs."""

from http import HTTPStatus
from unittest.mock import AsyncMock, patch

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.channels.models import (
    Channel,
    ChannelKind,
    Character,
    CharacterStatus,
    PublishMode,
)
from server.apps.pipelines.models import CastDesignStatus, PipelineRun, RunCast


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(
        name='Character Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def character(channel: Channel) -> Character:
    return Character.objects.create(
        channel=channel,
        name='Detective Mara',
        appearance_prompt='tall detective in a trench coat',
    )


@pytest.fixture
def run(channel: Channel, db) -> PipelineRun:  # type: ignore[no-untyped-def]
    from server.apps.pipelines.models import PipelineBlueprint, PipelineKind

    blueprint = PipelineBlueprint.objects.create(
        name='longform_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
    )
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='Test topic',
    )


@pytest.fixture
def cast_member(run: PipelineRun, character: Character) -> RunCast:
    return RunCast.objects.create(
        run=run,
        character=character,
        role='protagonist',
        design_status=CastDesignStatus.PROPOSED,
    )


@pytest.mark.django_db
def test_niche_config_get_and_patch(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    url = reverse(
        'api:channels_api:channel-niche',
        kwargs={'channel_id': channel.id},
    )
    get_response = dmr_client.get(url, headers=auth_headers)
    assert get_response.status_code == HTTPStatus.OK

    patch_response = dmr_client.patch(
        url,
        data={'audience': 'history buffs', 'angle': 'deep dives'},
        headers=auth_headers,
    )
    assert patch_response.status_code == HTTPStatus.OK
    assert patch_response.json()['audience'] == 'history buffs'


@pytest.mark.django_db
def test_character_crud(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    create_response = dmr_client.post(
        reverse('api:channels_api:character-collection'),
        data={
            'name': 'King Alaric',
            'channel_id': str(channel.id),
            'appearance_prompt': 'bearded king',
        },
        headers=auth_headers,
    )
    assert create_response.status_code == HTTPStatus.CREATED
    character_id = create_response.json()['id']

    detail_response = dmr_client.get(
        reverse(
            'api:channels_api:character-detail',
            kwargs={'character_id': character_id},
        ),
        headers=auth_headers,
    )
    assert detail_response.status_code == HTTPStatus.OK
    assert detail_response.json()['name'] == 'King Alaric'


@pytest.mark.django_db
def test_character_round_and_approve(
    dmr_client: DMRClient,
    character: Character,
    auth_headers: dict[str, str],
) -> None:
    session_response = dmr_client.post(
        reverse(
            'api:channels_api:character-session-collection',
            kwargs={'character_id': character.id},
        ),
        headers=auth_headers,
    )
    assert session_response.status_code == HTTPStatus.CREATED
    session_id = session_response.json()['id']

    get_session = dmr_client.get(
        reverse(
            'api:channels_api:character-session-detail',
            kwargs={
                'character_id': character.id,
                'session_id': session_id,
            },
        ),
        headers=auth_headers,
    )
    assert get_session.status_code == HTTPStatus.OK
    assert get_session.json()['id'] == session_id

    mock_result = {'url': 'https://example.com/image.png', 'seed': 1}
    with (
        patch(
            'server.apps.channels.character_studio.fal_client.generate_image',
            new=AsyncMock(return_value=mock_result),
        ),
        patch(
            'server.apps.channels.character_studio._download_image',
            return_value=b'\x89PNG',
        ),
    ):
        round_response = dmr_client.post(
            reverse(
                'api:channels_api:character-round',
                kwargs={
                    'character_id': character.id,
                    'session_id': session_id,
                },
            ),
            data={'prompt': 'hero portrait', 'n': 1},
            headers=auth_headers,
        )
    assert round_response.status_code == HTTPStatus.OK
    asset_id = round_response.json()['candidate_asset_ids'][0]
    assert LibraryAsset.objects.filter(
        id=asset_id,
        kind=LibraryAssetKind.CHARACTER_REF,
    ).exists()

    approve_response = dmr_client.post(
        reverse(
            'api:channels_api:character-approve',
            kwargs={'character_id': character.id},
        ),
        data={'winning_asset_id': asset_id},
        headers=auth_headers,
    )
    assert approve_response.status_code == HTTPStatus.OK
    assert approve_response.json()['status'] == CharacterStatus.APPROVED


@pytest.mark.django_db
def test_run_cast_list_and_approve(
    dmr_client: DMRClient,
    run: PipelineRun,
    cast_member: RunCast,
    auth_headers: dict[str, str],
) -> None:
    list_response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-cast-collection',
            kwargs={'run_id': run.id},
        ),
        headers=auth_headers,
    )
    assert list_response.status_code == HTTPStatus.OK
    assert list_response.json()['total'] == 1

    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name='Approved ref',
        file='library/test.png',
    )
    approve_response = dmr_client.post(
        reverse(
            'api:pipelines_api:run-cast-approve',
            kwargs={'run_id': run.id, 'cast_id': cast_member.id},
        ),
        data={'winning_asset_id': str(asset.id)},
        headers=auth_headers,
    )
    assert approve_response.status_code == HTTPStatus.OK
    assert approve_response.json()['design_status'] == CastDesignStatus.APPROVED


@pytest.mark.django_db
def test_character_list_filters(
    dmr_client: DMRClient,
    channel: Channel,
    character: Character,
    auth_headers: dict[str, str],
) -> None:
    """Character list supports channel and status filters."""
    Character.objects.create(
        channel=channel,
        name='Draft Character',
        appearance_prompt='draft',
        status=CharacterStatus.DRAFT,
    )
    url = (
        f'{reverse("api:channels_api:character-collection")}'
        f'?channel={channel.id}&status={CharacterStatus.APPROVED}'
    )
    response = dmr_client.get(url, headers=auth_headers)

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body['total'] == 0


@pytest.mark.django_db
def test_character_detail_404(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    """GET missing character returns 404."""
    import uuid

    response = dmr_client.get(
        reverse(
            'api:channels_api:character-detail',
            kwargs={'character_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_character_promote_before_approve_422(
    dmr_client: DMRClient,
    character: Character,
    auth_headers: dict[str, str],
) -> None:
    """Promote before approval returns 422."""
    response = dmr_client.post(
        reverse(
            'api:channels_api:character-promote',
            kwargs={'character_id': character.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_character_expand_without_hero_422(
    dmr_client: DMRClient,
    character: Character,
    auth_headers: dict[str, str],
) -> None:
    """Sheet expand without hero reference returns 422."""
    response = dmr_client.post(
        reverse(
            'api:channels_api:character-sheet-expand',
            kwargs={'character_id': character.id},
        ),
        data={'labels': ['front view']},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_run_cast_patch_session_and_round(
    dmr_client: DMRClient,
    run: PipelineRun,
    cast_member: RunCast,
    auth_headers: dict[str, str],
) -> None:
    """Run cast supports PATCH, session, and round generation."""
    patch_response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-cast-detail',
            kwargs={'run_id': run.id, 'cast_id': cast_member.id},
        ),
        data={'role': 'antagonist'},
        headers=auth_headers,
    )
    assert patch_response.status_code == HTTPStatus.OK
    assert patch_response.json()['role'] == 'antagonist'

    session_response = dmr_client.post(
        reverse(
            'api:pipelines_api:run-cast-session',
            kwargs={'run_id': run.id, 'cast_id': cast_member.id},
        ),
        headers=auth_headers,
    )
    assert session_response.status_code == HTTPStatus.CREATED
    session_id = session_response.json()['id']

    get_session = dmr_client.get(
        reverse(
            'api:pipelines_api:run-cast-session-detail',
            kwargs={
                'run_id': run.id,
                'cast_id': cast_member.id,
                'session_id': session_id,
            },
        ),
        headers=auth_headers,
    )
    assert get_session.status_code == HTTPStatus.OK
    assert get_session.json()['character_id'] == str(cast_member.character_id)

    mock_result = {'url': 'https://example.com/cast.png', 'seed': 2}
    with (
        patch(
            'server.apps.channels.character_studio.fal_client.generate_image',
            new=AsyncMock(return_value=mock_result),
        ),
        patch(
            'server.apps.channels.character_studio._download_image',
            return_value=b'\x89PNG',
        ),
    ):
        round_response = dmr_client.post(
            reverse(
                'api:pipelines_api:run-cast-round',
                kwargs={
                    'run_id': run.id,
                    'cast_id': cast_member.id,
                    'session_id': session_id,
                },
            ),
            data={'prompt': 'cast portrait', 'n': 1},
            headers=auth_headers,
        )
    assert round_response.status_code == HTTPStatus.OK
    assert round_response.json()['candidate_asset_ids']


@pytest.mark.django_db
def test_character_session_detail_wrong_character_404(
    dmr_client: DMRClient,
    character: Character,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """GET session for wrong character returns 404."""
    other = Character.objects.create(channel=channel, name='Other')
    session_id = dmr_client.post(
        reverse(
            'api:channels_api:character-session-collection',
            kwargs={'character_id': other.id},
        ),
        headers=auth_headers,
    ).json()['id']
    response = dmr_client.get(
        reverse(
            'api:channels_api:character-session-detail',
            kwargs={
                'character_id': character.id,
                'session_id': session_id,
            },
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_run_cast_session_detail_wrong_cast_404(
    dmr_client: DMRClient,
    run: PipelineRun,
    cast_member: RunCast,
    character: Character,
    auth_headers: dict[str, str],
) -> None:
    """GET cast session for mismatched cast returns 404."""
    other = Character.objects.create(channel=run.channel, name='Other Cast')
    other_cast = RunCast.objects.create(run=run, character=other, role='extra')
    session_id = dmr_client.post(
        reverse(
            'api:pipelines_api:run-cast-session',
            kwargs={'run_id': run.id, 'cast_id': other_cast.id},
        ),
        headers=auth_headers,
    ).json()['id']
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-cast-session-detail',
            kwargs={
                'run_id': run.id,
                'cast_id': cast_member.id,
                'session_id': session_id,
            },
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_run_cast_approve_without_winning_asset_422(
    dmr_client: DMRClient,
    run: PipelineRun,
    cast_member: RunCast,
    auth_headers: dict[str, str],
) -> None:
    """Run cast approve without winning_asset_id returns 422."""
    response = dmr_client.post(
        reverse(
            'api:pipelines_api:run-cast-approve',
            kwargs={'run_id': run.id, 'cast_id': cast_member.id},
        ),
        data={},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.django_db
def test_run_cast_404(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """PATCH missing cast member returns 404."""
    import uuid

    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-cast-detail',
            kwargs={'run_id': run.id, 'cast_id': uuid.uuid4()},
        ),
        data={'role': 'missing'},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_run_cast_patch_design_status(
    dmr_client: DMRClient,
    run: PipelineRun,
    cast_member: RunCast,
    auth_headers: dict[str, str],
) -> None:
    """PATCH run cast can update design_status."""
    response = dmr_client.patch(
        reverse(
            'api:pipelines_api:run-cast-detail',
            kwargs={'run_id': run.id, 'cast_id': cast_member.id},
        ),
        data={'design_status': CastDesignStatus.APPROVED},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()['design_status'] == CastDesignStatus.APPROVED


@pytest.mark.django_db
def test_run_cast_approve_404(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """POST approve for missing cast returns 404."""
    import uuid

    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name='Missing cast ref',
        file='library/missing.png',
    )
    response = dmr_client.post(
        reverse(
            'api:pipelines_api:run-cast-approve',
            kwargs={'run_id': run.id, 'cast_id': uuid.uuid4()},
        ),
        data={'winning_asset_id': str(asset.id)},
        headers=auth_headers,
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_character_session_detail_not_found(
    dmr_client: DMRClient,
    character: Character,
    auth_headers: dict[str, str],
) -> None:
    """GET missing session returns 404."""
    import uuid

    response = dmr_client.get(
        reverse(
            'api:channels_api:character-session-detail',
            kwargs={
                'character_id': character.id,
                'session_id': uuid.uuid4(),
            },
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_run_cast_session_detail_not_found(
    dmr_client: DMRClient,
    run: PipelineRun,
    cast_member: RunCast,
    auth_headers: dict[str, str],
) -> None:
    """GET missing cast session returns 404."""
    import uuid

    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-cast-session-detail',
            kwargs={
                'run_id': run.id,
                'cast_id': cast_member.id,
                'session_id': uuid.uuid4(),
            },
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND
