"""Tests for clip brand template API and application."""

import uuid
from http import HTTPStatus

import pytest
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.channels.models import Channel, ChannelKind
from server.apps.clips.brand_templates import apply_brand_template_to_candidate
from server.apps.clips.logic.constants import (
    CandidateStatus,
    CaptionStyle,
    RenderFormat,
)
from server.apps.clips.models import ClipBrandTemplate, ClipCandidate
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
)


@pytest.fixture
def channel(db) -> Channel:  # type: ignore[no-untyped-def]
    return Channel.objects.create(
        name='Brand Channel',
        kind=ChannelKind.CLIPPING,
    )


@pytest.mark.django_db
def test_brand_template_crud(
    dmr_client: DMRClient,
    channel: Channel,
    auth_headers: dict[str, str],
) -> None:
    create_resp = dmr_client.post(
        reverse('api:clips:brand-template-collection'),
        data={
            'channel_id': str(channel.id),
            'name': 'Shorts default',
            'caption_preset_key': 'karaoke',
            'render_format': RenderFormat.VERTICAL_9_16,
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == HTTPStatus.CREATED
    template_id = create_resp.json()['id']
    assert create_resp.json()['caption_preset_key'] == 'karaoke'

    list_resp = dmr_client.get(
        reverse('api:clips:brand-template-collection'),
        query_params={'channel_id': str(channel.id)},
        headers=auth_headers,
    )
    assert list_resp.status_code == HTTPStatus.OK
    assert list_resp.json()['total'] == 1

    patch_resp = dmr_client.patch(
        reverse(
            'api:clips:brand-template-detail',
            kwargs={'template_id': template_id},
        ),
        data={'name': 'Shorts v2', 'auto_transitions': True},
        headers=auth_headers,
    )
    assert patch_resp.status_code == HTTPStatus.OK
    assert patch_resp.json()['name'] == 'Shorts v2'
    assert patch_resp.json()['auto_transitions'] is True

    dup_resp = dmr_client.post(
        reverse(
            'api:clips:brand-template-duplicate',
            kwargs={'template_id': template_id},
        ),
        headers=auth_headers,
    )
    assert dup_resp.status_code == HTTPStatus.CREATED
    assert '(copy)' in dup_resp.json()['name']


@pytest.mark.django_db
def test_brand_template_not_found(
    dmr_client: DMRClient,
    auth_headers: dict[str, str],
) -> None:
    response = dmr_client.get(
        reverse(
            'api:clips:brand-template-detail',
            kwargs={'template_id': uuid.uuid4()},
        ),
        headers=auth_headers,
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_apply_brand_template_to_candidate(channel: Channel) -> None:
    bp = PipelineBlueprint.objects.create(
        name='clip-brand-apply',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='brand apply',
    )
    template = ClipBrandTemplate.objects.create(
        channel=channel,
        name='Apply me',
        caption_preset_key='karaoke',
        render_format=RenderFormat.SQUARE_1_1,
        foreground_treatment='CONTAIN',
        background_mode='SOLID',
        background_color='#101010',
        blur_strength=12,
        auto_transitions=True,
    )
    candidate = ClipCandidate.objects.create(
        run=run,
        start_sec=0,
        end_sec=30,
        title='Moment',
        status=CandidateStatus.PROPOSED,
    )
    assert apply_brand_template_to_candidate(candidate, str(template.id))
    candidate.refresh_from_db()
    assert candidate.layout_config.render_format == RenderFormat.SQUARE_1_1
    assert candidate.layout_config.foreground_treatment == 'CONTAIN'
    assert candidate.layout_config.background_mode == 'SOLID'
    assert candidate.layout_config.background_color == '#101010'
    assert candidate.layout_config.blur_strength == 12
    assert candidate.style_config.caption_style == CaptionStyle.KARAOKE_HIGHLIGHT
    assert candidate.style_config.intro_transition == 'FADE_BLACK'
