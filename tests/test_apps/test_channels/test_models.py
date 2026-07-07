import pytest

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    Character,
    CharacterDesignMode,
    CharacterStatus,
    PublishMode,
)


# Non-DB: verify enum values and field defaults that don't need FK resolution
def test_channel_kind_choices_include_all() -> None:
    assert set(ChannelKind.values) == {'LONGFORM', 'SHORTS', 'CLIPPING'}


def test_publish_mode_default_is_review() -> None:
    assert PublishMode.REVIEW == 'review'


def test_character_design_mode_has_three_choices() -> None:
    assert set(CharacterDesignMode.values) == {'interactive', 'auto', 'none'}


def test_character_status_choices() -> None:
    assert CharacterStatus.DRAFT == 'DRAFT'
    assert CharacterStatus.APPROVED == 'APPROVED'


def test_channel_str_in_memory() -> None:
    ch = Channel(name='History Hub', kind=ChannelKind.LONGFORM)
    assert str(ch) == 'History Hub'


def test_channel_wpm_default() -> None:
    ch = Channel(name='Test', kind=ChannelKind.LONGFORM)
    assert ch.wpm == 158
    assert ch.is_active is True


# DB tests — activated in Task 5 after migrations are applied
@pytest.mark.django_db
def test_channel_creation_persists() -> None:
    ch = Channel.objects.create(name='Test Channel', kind=ChannelKind.LONGFORM)
    assert ch.id is not None
    assert ch.gates == []
    assert ch.publish_mode == PublishMode.REVIEW
    assert ch.character_design_mode == CharacterDesignMode.INTERACTIVE


@pytest.mark.django_db
def test_assembly_style_config_defaults_and_str() -> None:
    from server.apps.channels.models import AssemblyStyleConfig

    channel = Channel.objects.create(name='Style Ch', kind=ChannelKind.LONGFORM)
    style = AssemblyStyleConfig.objects.create(channel=channel)
    assert style.min_cuts_per_minute == 4
    assert style.max_cuts_per_minute == 8
    assert 'Style Ch' in str(style)


@pytest.mark.django_db
def test_channel_assembly_style_camera_movements_property() -> None:
    from server.apps.channels.models import AssemblyStyleConfig

    channel = Channel.objects.create(name='Prop Ch', kind=ChannelKind.LONGFORM)
    assert channel.assembly_style_camera_movements == []
    AssemblyStyleConfig.objects.create(
        channel=channel,
        camera_movements=['pan_left', 'push_in'],
    )
    channel.refresh_from_db()
    assert channel.assembly_style_camera_movements == ['pan_left', 'push_in']


@pytest.mark.django_db
def test_character_defaults_persisted() -> None:
    from decimal import Decimal

    from server.apps.channels.models import CharacterOrigin

    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    char = Character.objects.create(
        channel=ch,
        name='King Alaric',
        appearance_prompt='tall',
    )
    assert char.status == CharacterStatus.DRAFT
    assert char.origin == CharacterOrigin.RUN
    assert char.total_creation_cost_usd == Decimal(0)


@pytest.mark.django_db
def test_niche_config_links_to_channel() -> None:
    from server.apps.channels.models import NicheConfig

    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    nc = NicheConfig.objects.create(
        channel=ch,
        audience='adults',
        angle='historical',
    )
    assert nc.channel_id == ch.id
    assert nc.banned_topics == []


@pytest.mark.django_db
def test_channel_branding_defaults() -> None:
    from server.apps.channels.models import ChannelBranding

    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    branding = ChannelBranding.objects.create(channel=ch)
    assert branding.fonts.count() == 0
    assert branding.watermark_opacity == 0.6
    assert branding.music_pool_tags == []
    assert branding.thumbnail_palette == {}


@pytest.mark.django_db
def test_character_generation_session_rounds_default_empty() -> None:
    from server.apps.channels.models import CharacterGenerationSession

    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    char = Character.objects.create(channel=ch, name='K', appearance_prompt='p')
    session = CharacterGenerationSession.objects.create(character=char)
    assert session.rounds == []


@pytest.mark.django_db
def test_str_methods_for_channel_related_models() -> None:
    from server.apps.assets.models import LibraryAsset, LibraryAssetKind
    from server.apps.channels.models import (
        ChannelBranding,
        CharacterGenerationSession,
        CharacterSheetItem,
        NicheConfig,
        YouTubeCredential,
    )

    ch = Channel.objects.create(name='Doc Hub', kind=ChannelKind.LONGFORM)
    nc = NicheConfig.objects.create(
        channel=ch,
        audience='adults',
        angle='historical',
    )
    assert 'Doc Hub' in str(nc)

    yt = YouTubeCredential.objects.create(
        channel=ch,
        access_token='tok',
        refresh_token='ref',
    )
    assert 'Doc Hub' in str(yt)

    branding = ChannelBranding.objects.create(channel=ch)
    assert 'Doc Hub' in str(branding)

    char = Character.objects.create(
        channel=ch,
        name='Hero',
        appearance_prompt='tall',
    )
    assert str(char) == 'Hero'

    asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.CHARACTER_REF,
        name='ref.png',
    )
    sheet_item = CharacterSheetItem.objects.create(
        character=char,
        asset=asset,
        label='front',
    )
    assert 'Hero' in str(sheet_item)
    assert 'front' in str(sheet_item)

    session = CharacterGenerationSession.objects.create(character=char)
    assert 'Hero' in str(session)
