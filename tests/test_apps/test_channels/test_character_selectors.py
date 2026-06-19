"""Tests for character selector helpers."""

import pytest

from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.channels.character_selectors import (
    get_character_detail,
    get_character_session,
    list_characters,
)
from server.apps.channels.models import (
    Channel,
    ChannelKind,
    Character,
    CharacterGenerationSession,
    CharacterStatus,
    PublishMode,
)


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(
        name='Selector Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def other_channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(
        name='Other Channel',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def hero_asset(channel: Channel) -> LibraryAsset:
    return LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name='Hero',
        file='library/hero.png',
        channel=channel,
    )


@pytest.fixture
def character(channel: Channel, hero_asset: LibraryAsset) -> Character:
    return Character.objects.create(
        channel=channel,
        name='Selector Hero',
        appearance_prompt='tall warrior',
        status=CharacterStatus.APPROVED,
        hero_ref=hero_asset,
    )


@pytest.mark.django_db
def test_list_characters_filters_by_channel_and_status(
    channel: Channel,
    other_channel: Channel,
    character: Character,
) -> None:
    """list_characters honors channel_id and status filters."""
    Character.objects.create(
        channel=other_channel,
        name='Draft Elsewhere',
        appearance_prompt='other',
        status=CharacterStatus.DRAFT,
    )
    Character.objects.create(
        channel=channel,
        name='Draft Here',
        appearance_prompt='draft',
        status=CharacterStatus.DRAFT,
    )

    by_channel = list_characters(channel_id=str(channel.id))
    assert by_channel.total == 2

    approved = list_characters(
        channel_id=str(channel.id),
        status=CharacterStatus.APPROVED,
    )
    assert approved.total == 1
    assert approved.items[0].name == 'Selector Hero'
    assert approved.items[0].hero_ref_asset_id == str(character.hero_ref_id)


@pytest.mark.django_db
def test_get_character_detail_includes_optional_fields(
    character: Character,
) -> None:
    """get_character_detail maps hero ref and channel."""
    detail = get_character_detail(str(character.id))

    assert detail.name == 'Selector Hero'
    assert detail.channel_id == str(character.channel_id)
    assert detail.hero_ref_asset_id == str(character.hero_ref_id)


@pytest.mark.django_db
def test_get_character_session_maps_rounds(character: Character) -> None:
    """get_character_session converts stored round JSON."""
    session = CharacterGenerationSession.objects.create(
        character=character,
        rounds=[
            {
                'prompt': 'portrait',
                'model': 'fal-ai/flux/dev',
                'n': 2,
                'cost_usd': '0.12',
                'candidate_asset_ids': ['a1', 'a2'],
                'picked': 'a1',
            },
            'invalid-round',
        ],
    )

    payload = get_character_session(str(session.id))

    assert payload.character_id == str(character.id)
    assert len(payload.rounds) == 2
    assert payload.rounds[0].prompt == 'portrait'
    assert payload.rounds[0].candidate_asset_ids == ['a1', 'a2']
    assert payload.rounds[0].picked == 'a1'
    assert payload.rounds[1].candidate_asset_ids == []
