"""Tests for per-channel footage sourcing configuration."""

import pytest

from server.apps.channels.models import (
    Channel,
    ChannelKind,
    FootageSourcingConfig,
    RerankMode,
    SourcingMode,
)


@pytest.fixture
def channel(db: None) -> Channel:
    return Channel.objects.create(name='Doc Channel', kind=ChannelKind.LONGFORM)


@pytest.mark.django_db
def test_defaults_are_documentary_safe(channel: Channel) -> None:
    """A config created with no arguments is usable as-is."""
    config = FootageSourcingConfig.objects.create(channel=channel)
    assert config.ai_fallback_enabled is True
    assert config.rerank_mode == RerankMode.VISION
    assert config.sourcing_mode == SourcingMode.STOCK_FIRST
    assert config.candidates_per_scene == 8
    assert config.min_clip_width == 1280
    assert config.min_clip_duration_s == pytest.approx(3.0)
    assert config.require_attribution is True
    assert config.enabled_providers == []


@pytest.mark.django_db
def test_provider_order_is_preserved(channel: Channel) -> None:
    """enabled_providers is an ordered priority list, not a set."""
    config = FootageSourcingConfig.objects.create(
        channel=channel,
        enabled_providers=['wikimedia', 'openverse', 'pexels'],
    )
    config.refresh_from_db()
    assert config.enabled_providers == ['wikimedia', 'openverse', 'pexels']


@pytest.mark.django_db
def test_channel_without_config_gets_unsaved_defaults(
    channel: Channel,
) -> None:
    """Channels with no config row still resolve to usable defaults."""
    config = channel.footage_sourcing_or_default()
    assert config.pk is None
    assert config.ai_fallback_enabled is True
    assert config.rerank_mode == RerankMode.VISION


@pytest.mark.django_db
def test_channel_with_config_returns_the_saved_row(channel: Channel) -> None:
    """An existing config row wins over the defaults."""
    FootageSourcingConfig.objects.create(
        channel=channel,
        ai_fallback_enabled=False,
    )
    config = channel.footage_sourcing_or_default()
    assert config.pk is not None
    assert config.ai_fallback_enabled is False


@pytest.mark.django_db
def test_invalid_sourcing_mode_is_rejected(channel: Channel) -> None:
    """The check constraint rejects an unknown sourcing mode."""
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        FootageSourcingConfig.objects.create(
            channel=channel,
            sourcing_mode='not_a_mode',
        )
