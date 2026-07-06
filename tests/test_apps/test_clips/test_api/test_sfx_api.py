"""Tests for ClipTimedSfx API endpoints."""

from http import HTTPStatus

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.assets.models import LibraryAsset, LibraryAssetKind
from server.apps.clips.models import ClipCandidate


@pytest.fixture
def channel(db):  # type: ignore[no-untyped-def]
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
        PublishMode,
    )

    return Channel.objects.create(
        name='SFX Test',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def blueprint(db):  # type: ignore[no-untyped-def]
    from server.apps.pipelines.models import (
        PipelineBlueprint,
        PipelineKind,
    )

    return PipelineBlueprint.objects.create(
        name='clipping_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )


@pytest.fixture
def run(channel, blueprint):  # type: ignore[no-untyped-def]
    from server.apps.pipelines.models import PipelineRun

    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='https://youtube.com/watch?v=test',
    )


@pytest.fixture
def candidate(run):  # type: ignore[no-untyped-def]
    return ClipCandidate.objects.create(
        run=run,
        start_sec=10.0,
        end_sec=70.0,
        title='SFX Clip',
    )


@pytest.mark.django_db
def test_create_and_list_sfx(
    dmr_client: DMRClient,
    candidate: ClipCandidate,
    auth_headers: dict[str, str],
) -> None:
    """SFX drops can be created, listed, patched, and deleted."""
    sfx_asset = LibraryAsset.objects.create(
        kind=LibraryAssetKind.SFX,
        name='whoosh.mp3',
        file=ContentFile(b'audio', name='whoosh.mp3'),
    )

    create_resp = dmr_client.post(
        reverse(
            'clips:sfx_list',
            kwargs={'candidate_id': candidate.id},
        ),
        data={'sfx_asset_id': str(sfx_asset.id), 'start_sec': 3.0},
        headers=auth_headers,
    )
    assert create_resp.status_code == HTTPStatus.CREATED
    sfx_id = create_resp.json()['id']

    list_resp = dmr_client.get(
        reverse(
            'clips:sfx_list',
            kwargs={'candidate_id': candidate.id},
        ),
        headers=auth_headers,
    )
    assert list_resp.status_code == HTTPStatus.OK
    assert list_resp.json()['total'] == 1

    patch_resp = dmr_client.patch(
        reverse(
            'clips:sfx_detail',
            kwargs={
                'candidate_id': candidate.id,
                'sfx_id': sfx_id,
            },
        ),
        data={'volume_db': -5.0},
        headers=auth_headers,
    )
    assert patch_resp.status_code == HTTPStatus.OK
    assert patch_resp.json()['volume_db'] == -5.0

    delete_resp = dmr_client.delete(
        reverse(
            'clips:sfx_detail',
            kwargs={
                'candidate_id': candidate.id,
                'sfx_id': sfx_id,
            },
        ),
        headers=auth_headers,
    )
    assert delete_resp.status_code == HTTPStatus.NO_CONTENT
