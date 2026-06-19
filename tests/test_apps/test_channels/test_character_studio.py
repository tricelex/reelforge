"""Unit tests for CharacterStudioService."""

from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.channels.character_studio import (
    CharacterStudioService,
    _download_image,
    _ref_image_url,
)
from server.apps.channels.logic.value_objects import (
    CharacterApprovePayload,
    CharacterPatchPayload,
    CharacterRoundCreatePayload,
    CharacterSheetExpandPayload,
)
from server.apps.channels.models import (
    Channel,
    ChannelKind,
    Character,
    CharacterOrigin,
    CharacterStatus,
    PublishMode,
)


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(
        name='Studio Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def character(channel: Channel) -> Character:
    return Character.objects.create(
        channel=channel,
        name='Studio Hero',
        appearance_prompt='tall hero',
    )


@pytest.fixture
def service() -> CharacterStudioService:
    return CharacterStudioService()


@pytest.mark.django_db
def test_download_image(service: CharacterStudioService) -> None:
    """Download helper fetches bytes from a URL."""
    mock_response = MagicMock()
    mock_response.content = b'\x89PNG'
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_response

    with patch(
        'server.apps.channels.character_studio.httpx.Client',
        return_value=mock_client,
    ):
        assert _download_image('https://example.com/image.png') == b'\x89PNG'


@pytest.mark.django_db
def test_ref_image_url(
    service: CharacterStudioService,
    channel: Channel,
) -> None:
    """Ref helper returns None or asset file URL."""
    assert _ref_image_url(None) is None

    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name='Ref',
        channel=channel,
        file=ContentFile(b'png', name='ref.png'),
    )
    url = _ref_image_url(str(asset.id))
    assert url is not None


@pytest.mark.django_db
def test_patch_character_fields(
    service: CharacterStudioService,
    character: Character,
) -> None:
    """Patch updates name, prompt, persona, and status."""
    result = service.patch(
        str(character.id),
        CharacterPatchPayload(
            name='Renamed',
            appearance_prompt='new look',
            persona='brave',
            status=CharacterStatus.APPROVED,
        ),
    )
    assert result.name == 'Renamed'
    assert result.status == CharacterStatus.APPROVED


@pytest.mark.django_db
def test_approve_with_appearance_prompt(
    service: CharacterStudioService,
    character: Character,
    channel: Channel,
) -> None:
    """Approve can override appearance prompt."""
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name='Winner',
        channel=channel,
        file=ContentFile(b'png', name='win.png'),
    )
    payload = CharacterApprovePayload(
        winning_asset_id=str(asset.id),
        appearance_prompt='updated prompt',
    )
    result = service.approve(str(character.id), payload)
    assert result.status == CharacterStatus.APPROVED
    character.refresh_from_db()
    assert character.appearance_prompt == 'updated prompt'


@pytest.mark.django_db
def test_promote_approved_character(
    service: CharacterStudioService,
    character: Character,
    channel: Channel,
) -> None:
    """Promote moves approved character into library origin."""
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name='Hero',
        channel=channel,
        file=ContentFile(b'png', name='hero.png'),
    )
    character.status = CharacterStatus.APPROVED
    character.hero_ref_id = asset.id
    character.save()

    result = service.promote(str(character.id))
    assert result.origin == CharacterOrigin.LIBRARY
    character.refresh_from_db()
    assert character.source_run_id is None


@pytest.mark.django_db
def test_promote_requires_approved(
    service: CharacterStudioService,
    character: Character,
) -> None:
    """Promote rejects draft characters."""
    with pytest.raises(ValidationError, match='approved'):
        service.promote(str(character.id))


@pytest.mark.django_db
def test_expand_sheet_success(
    service: CharacterStudioService,
    character: Character,
    channel: Channel,
) -> None:
    """Expand sheet generates labeled variants from hero ref."""
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name='Hero',
        channel=channel,
        file=ContentFile(b'png', name='hero.png'),
    )
    character.status = CharacterStatus.APPROVED
    character.hero_ref_id = asset.id
    character.appearance_prompt = 'detective'
    character.save()

    payload = CharacterSheetExpandPayload(labels=['front view'])

    mock_result = {'url': 'https://example.com/sheet.png', 'seed': 1}
    with (
        patch(
            'server.apps.channels.character_studio.fal_client.generate_image',
            new=AsyncMock(return_value=mock_result),
        ),
        patch(
            'server.apps.channels.character_studio._download_image',
            return_value=b'\x89PNG',
        ),
        patch(
            'server.apps.channels.character_studio._ref_image_url',
            return_value='https://example.com/ref.png',
        ),
    ):
        result = service.expand_sheet(str(character.id), payload)

    assert len(result.items) == 1
    assert result.items[0].label == 'front view'


@pytest.mark.django_db
def test_expand_sheet_missing_prompt(
    service: CharacterStudioService,
    character: Character,
    channel: Channel,
) -> None:
    """Expand sheet requires appearance prompt."""
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name='Hero',
        channel=channel,
        file=ContentFile(b'png', name='hero.png'),
    )
    character.hero_ref_id = asset.id
    character.appearance_prompt = ''
    character.save()

    payload = CharacterSheetExpandPayload(labels=['side view'])

    with pytest.raises(ValidationError, match='appearance prompt'):
        service.expand_sheet(str(character.id), payload)


@pytest.mark.django_db
def test_generate_round_with_ref_asset(
    service: CharacterStudioService,
    character: Character,
    channel: Channel,
) -> None:
    """Generate round uses reference asset URL when provided."""
    ref = LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name='Ref',
        channel=channel,
        file=ContentFile(b'png', name='ref.png'),
    )
    session = service.start_session(str(character.id))
    payload = CharacterRoundCreatePayload(
        prompt='portrait',
        n=1,
        ref_asset_ids=[str(ref.id)],
    )

    mock_result = {'url': 'https://example.com/gen.png', 'seed': 1}
    with (
        patch(
            'server.apps.channels.character_studio.fal_client.generate_image',
            new=AsyncMock(return_value=mock_result),
        ),
        patch(
            'server.apps.channels.character_studio._download_image',
            return_value=b'\x89PNG',
        ),
        patch(
            'server.apps.channels.character_studio._ref_image_url',
            return_value='https://example.com/ref.png',
        ),
    ):
        result = service.generate_round(
            str(character.id),
            session.id,
            payload,
        )

    assert result.candidate_asset_ids


@pytest.mark.django_db
def test_character_promote_and_expand_api(
    dmr_client: DMRClient,
    character: Character,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    """Promote and expand endpoints succeed for approved characters."""
    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name='Hero',
        channel=channel,
        file=ContentFile(b'png', name='hero.png'),
    )
    character.status = CharacterStatus.APPROVED
    character.hero_ref_id = asset.id
    character.appearance_prompt = 'hero'
    character.save()

    promote_resp = dmr_client.post(
        reverse(
            'api:channels_api:character-promote',
            kwargs={'character_id': character.id},
        ),
        headers=auth_headers,
    )
    assert promote_resp.status_code == HTTPStatus.OK

    mock_result = {'url': 'https://example.com/sheet.png', 'seed': 1}
    with (
        patch(
            'server.apps.channels.character_studio.fal_client.generate_image',
            new=AsyncMock(return_value=mock_result),
        ),
        patch(
            'server.apps.channels.character_studio._download_image',
            return_value=b'\x89PNG',
        ),
        patch(
            'server.apps.channels.character_studio._ref_image_url',
            return_value='https://example.com/ref.png',
        ),
    ):
        expand_resp = dmr_client.post(
            reverse(
                'api:channels_api:character-sheet-expand',
                kwargs={'character_id': character.id},
            ),
            data={'labels': ['profile']},
            headers=auth_headers,
        )
    assert expand_resp.status_code == HTTPStatus.OK
