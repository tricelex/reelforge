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
@pytest.mark.skip(reason='Migration applied in Task 5')
@pytest.mark.django_db
def test_channel_creation_persists() -> None:
    ch = Channel.objects.create(name='Test Channel', kind=ChannelKind.LONGFORM)
    assert ch.id is not None
    assert ch.gates == []
    assert ch.publish_mode == PublishMode.REVIEW
    assert ch.character_design_mode == CharacterDesignMode.INTERACTIVE


@pytest.mark.skip(reason='Migration applied in Task 5')
@pytest.mark.django_db
def test_character_defaults_persisted() -> None:
    from decimal import Decimal
    from server.apps.channels.models import CharacterOrigin
    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    char = Character.objects.create(channel=ch, name='King Alaric', appearance_prompt='tall')
    assert char.status == CharacterStatus.DRAFT
    assert char.origin == CharacterOrigin.RUN
    assert char.total_creation_cost_usd == Decimal('0')


@pytest.mark.skip(reason='Migration applied in Task 5')
@pytest.mark.django_db
def test_niche_config_links_to_channel() -> None:
    from server.apps.channels.models import NicheConfig
    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    nc = NicheConfig.objects.create(channel=ch, audience='adults', angle='historical')
    assert nc.channel_id == ch.id
    assert nc.banned_topics == []


@pytest.mark.skip(reason='Migration applied in Task 5')
@pytest.mark.django_db
def test_channel_branding_defaults() -> None:
    from server.apps.channels.models import ChannelBranding
    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    branding = ChannelBranding.objects.create(channel=ch)
    assert branding.fonts.count() == 0
    assert branding.watermark_opacity == 0.6
    assert branding.music_pool_tags == []
    assert branding.thumbnail_palette == {}


@pytest.mark.skip(reason='Migration applied in Task 5')
@pytest.mark.django_db
def test_character_generation_session_rounds_default_empty() -> None:
    from server.apps.channels.models import CharacterGenerationSession
    ch = Channel.objects.create(name='Ch', kind=ChannelKind.LONGFORM)
    char = Character.objects.create(channel=ch, name='K', appearance_prompt='p')
    session = CharacterGenerationSession.objects.create(character=char)
    assert session.rounds == []
