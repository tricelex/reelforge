"""Tests for blueprint name validation helpers."""

import pytest
from django.core.exceptions import ValidationError

from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.pipelines.blueprint_validation import (
    resolve_blueprint_name,
    validate_active_blueprint_name,
)
from server.apps.pipelines.models import PipelineBlueprint, PipelineKind


@pytest.fixture
def channel(db: None) -> Channel:
    return Channel.objects.create(
        name='Blueprint Val Channel',
        kind=ChannelKind.LONGFORM,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.mark.django_db
def test_validate_active_blueprint_name_rejects_empty() -> None:
    with pytest.raises(ValidationError, match='cannot be empty'):
        validate_active_blueprint_name('')


@pytest.mark.django_db
def test_validate_active_blueprint_name_rejects_missing() -> None:
    with pytest.raises(ValidationError, match='Blueprint not found'):
        validate_active_blueprint_name('missing_bp')


@pytest.mark.django_db
def test_resolve_blueprint_name_uses_channel_default(
    channel,
) -> None:
    PipelineBlueprint.objects.create(
        name='custom_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
        is_active=True,
    )
    channel.default_blueprint_name = 'custom_v1'
    channel.save(update_fields=['default_blueprint_name'])
    assert resolve_blueprint_name(
        channel_kind=channel.kind,
        channel_default=channel.default_blueprint_name,
        run_override=None,
    ) == 'custom_v1'


@pytest.mark.django_db
def test_resolve_blueprint_name_unmapped_kind(channel) -> None:
    with pytest.raises(ValidationError, match='No blueprint mapping'):
        resolve_blueprint_name(
            channel_kind='UNKNOWN',
            channel_default=None,
            run_override=None,
        )
