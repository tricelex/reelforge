"""Tests for the atomic ChannelSpec importer."""

from http import HTTPStatus
from unittest.mock import patch

import msgspec
import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.channel_research.logic.schemas import ChannelResearchAgentOutput
from server.apps.channel_research.logic.value_objects import ChannelSpecPayload
from server.apps.channels.models import (
    Channel,
    Character,
    CharacterStatus,
    NicheConfig,
)
from server.apps.pipelines.models import PipelineBlueprint, PipelineKind
from server.services.channel_spec_importer import import_channel_spec


@pytest.fixture
def longform_blueprint(db) -> PipelineBlueprint:  # type: ignore[no-untyped-def]
    """Active blueprint matching ChannelSpec default_blueprint_name."""
    return PipelineBlueprint.objects.create(
        name='longform_v1',
        kind=PipelineKind.LONGFORM,
        graph={'stages': []},
        is_active=True,
    )


def _payload_from_agent_output(
    agent_output: ChannelResearchAgentOutput,
    *,
    name: str | None = None,
    include_character: bool = True,
) -> ChannelSpecPayload:
    data = agent_output.channel_spec.model_dump()
    if name is not None:
        data['channel']['name'] = name
    data['channel']['character_design_mode'] = (
        'auto' if include_character else 'none'
    )
    data['niche']['style_tokens'] = ['archival maps', 'cold open']
    data['niche']['style_negatives'] = ['cartoon', 'anime']
    data['character'] = {
        'include': include_character,
        'name': 'Marcus',
        'appearance_prompt': (
            'Recurring host with fixed wardrobe, hair silhouette, '
            'and documentary lighting across every episode. '
            + ' '.join(['detail'] * 90)
        ),
        'persona': 'dry narrator',
        'status': CharacterStatus.APPROVED,
    }
    data['seed_ideas'] = [
        {
            'title': 'Seed One',
            'topic': 'first seed topic',
            'score': 0.9,
        },
    ]
    return msgspec.convert(data, type=ChannelSpecPayload)


@pytest.mark.django_db
def test_import_persists_visual_fields_and_approved_character(
    agent_output: ChannelResearchAgentOutput,
    longform_blueprint: PipelineBlueprint,
) -> None:
    """Importer saves niche visual lock and creates APPROVED character."""
    assert longform_blueprint.is_active
    result = import_channel_spec(
        _payload_from_agent_output(agent_output, name='Import Forge'),
    )
    channel = Channel.objects.get(id=result.channel_id)
    niche = NicheConfig.objects.get(channel=channel)
    assert niche.visual_medium == 'photoreal'
    assert niche.visual_bible
    assert 'cartoon' in niche.style_negatives
    assert 'archival maps' in niche.style_tokens
    character = Character.objects.get(channel=channel, name='Marcus')
    assert character.status == CharacterStatus.APPROVED
    assert character.hero_ref_id is None
    assert any(step.name == 'seeds' for step in result.steps)


@pytest.mark.django_db
def test_import_rolls_back_on_mid_transaction_failure(
    agent_output: ChannelResearchAgentOutput,
    longform_blueprint: PipelineBlueprint,
) -> None:
    """A failure after channel create rolls back the whole import."""
    assert longform_blueprint.name == 'longform_v1'
    payload = _payload_from_agent_output(
        agent_output,
        name='Rollback Forge',
    )
    with (
        patch(
            'server.services.channel_spec_importer._seed_character_and_ideas',
            side_effect=RuntimeError('boom'),
        ),
        pytest.raises(RuntimeError, match='boom'),
    ):
        import_channel_spec(payload)
    assert not Channel.objects.filter(name='Rollback Forge').exists()
    assert not Character.objects.filter(name='Marcus').exists()


@pytest.mark.django_db
def test_import_rejects_invalid_spec(
    agent_output: ChannelResearchAgentOutput,
) -> None:
    """Importer validates medium lock before writing."""
    data = agent_output.channel_spec.model_dump()
    data['niche']['visual_bible'] = 'too short'
    payload = msgspec.convert(data, type=ChannelSpecPayload)
    with pytest.raises(ValidationError):
        import_channel_spec(payload)
    assert not Channel.objects.filter(name='Forge History').exists()


@pytest.mark.django_db(transaction=True)
def test_import_api_creates_channel(
    dmr_client: DMRClient,
    agent_output: ChannelResearchAgentOutput,
    auth_headers: dict[str, str],
    longform_blueprint: PipelineBlueprint,
) -> None:
    """POST /api/channel-research/import/ returns channel_id + steps."""
    assert longform_blueprint.is_active
    payload = _payload_from_agent_output(
        agent_output,
        name='API Import Forge',
    )
    response = dmr_client.post(
        reverse('api:channel_research_api:import-spec'),
        data=msgspec.to_builtins(payload),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.CREATED
    body = response.json()
    assert body['channel_id']
    assert body['steps']
    assert Channel.objects.filter(id=body['channel_id']).exists()
