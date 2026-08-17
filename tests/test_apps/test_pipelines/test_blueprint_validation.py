"""Tests for blueprint name validation helpers."""

import pytest
from django.core.exceptions import ValidationError

from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.pipelines.blueprint_validation import (
    ensure_unique_blueprint_name,
    resolve_blueprint_name,
    validate_active_blueprint_name,
    validate_blueprint_graph,
    validate_blueprint_kind,
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
    assert (
        resolve_blueprint_name(
            channel_kind=channel.kind,
            channel_default=channel.default_blueprint_name,
            run_override=None,
        )
        == 'custom_v1'
    )


@pytest.mark.django_db
def test_validate_blueprint_kind_rejects_unknown() -> None:
    with pytest.raises(ValidationError, match='invalid blueprint kind'):
        validate_blueprint_kind('NOT_A_KIND')


@pytest.mark.django_db
def test_ensure_unique_blueprint_name_rejects_duplicate() -> None:
    PipelineBlueprint.objects.create(
        name='dup_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': [{'key': 'research', 'depends_on': []}]},
        is_active=True,
    )
    with pytest.raises(ValidationError, match='already exists'):
        ensure_unique_blueprint_name('dup_v1')


def test_validate_blueprint_graph_rejects_non_object() -> None:
    with pytest.raises(ValidationError, match='JSON object'):
        validate_blueprint_graph([])


def test_validate_blueprint_graph_rejects_empty_stages() -> None:
    with pytest.raises(ValidationError, match='non-empty list'):
        validate_blueprint_graph({'stages': []})


def test_validate_blueprint_graph_rejects_non_object_node() -> None:
    with pytest.raises(ValidationError, match='must be an object'):
        validate_blueprint_graph({'stages': ['research']})


def test_validate_blueprint_graph_rejects_empty_key() -> None:
    with pytest.raises(ValidationError, match='key is required'):
        validate_blueprint_graph({'stages': [{'key': '', 'depends_on': []}]})


def test_validate_blueprint_graph_rejects_duplicate_key() -> None:
    with pytest.raises(ValidationError, match='duplicate stage key'):
        validate_blueprint_graph(
            {
                'stages': [
                    {'key': 'research', 'depends_on': []},
                    {'key': 'research', 'depends_on': []},
                ],
            },
        )


def test_validate_blueprint_graph_rejects_unknown_queue() -> None:
    with pytest.raises(ValidationError, match='queue must be one of'):
        validate_blueprint_graph(
            {
                'stages': [
                    {
                        'key': 'research',
                        'depends_on': [],
                        'queue': 'celery',
                    },
                ],
            },
        )


def test_validate_blueprint_graph_rejects_bad_gate() -> None:
    with pytest.raises(ValidationError, match='gate must be a boolean'):
        validate_blueprint_graph(
            {
                'stages': [
                    {
                        'key': 'script_gate',
                        'depends_on': [],
                        'gate': 'yes',
                    },
                ],
            },
        )


def test_validate_blueprint_graph_rejects_bad_config() -> None:
    with pytest.raises(ValidationError, match='config must be an object'):
        validate_blueprint_graph(
            {
                'stages': [
                    {
                        'key': 'research',
                        'depends_on': [],
                        'config': [],
                    },
                ],
            },
        )


def test_validate_blueprint_graph_rejects_bad_fan_out() -> None:
    with pytest.raises(ValidationError, match='fan_out must be a string'):
        validate_blueprint_graph(
            {
                'stages': [
                    {
                        'key': 'tts',
                        'depends_on': [],
                        'fan_out': ['chapters'],
                    },
                ],
            },
        )


def test_validate_blueprint_graph_rejects_bad_depends_on_type() -> None:
    with pytest.raises(ValidationError, match='depends_on must be a list'):
        validate_blueprint_graph(
            {
                'stages': [
                    {'key': 'research', 'depends_on': 'outline'},
                ],
            },
        )


def test_validate_blueprint_graph_accepts_valid_graph() -> None:
    graph = {
        'stages': [
            {'key': 'research', 'depends_on': [], 'queue': 'api'},
            {
                'key': 'script_gate',
                'depends_on': ['research'],
                'gate': True,
                'config': {},
                'fan_out': 'scenes',
            },
        ],
    }
    assert validate_blueprint_graph(graph) == graph


@pytest.mark.django_db
def test_resolve_blueprint_name_unmapped_kind(channel) -> None:
    with pytest.raises(ValidationError, match='No blueprint mapping'):
        resolve_blueprint_name(
            channel_kind='UNKNOWN',
            channel_default=None,
            run_override=None,
        )
