"""Tests for deferred pipeline read endpoints."""

import json
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from dmr.test import DMRClient

from server.apps.assets.models import Asset, AssetKind
from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    StageExecution,
    StageStatus,
)


@pytest.fixture
def channel(db: None) -> Channel:
    """Clipping channel for deferred API tests."""
    return Channel.objects.create(
        name='Deferred API Channel',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )


@pytest.fixture
def blueprint(db: None) -> PipelineBlueprint:
    """Active clipping blueprint."""
    return PipelineBlueprint.objects.create(
        name='deferred_clip_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
        is_active=True,
        version=1,
    )


@pytest.fixture
def run(channel: Channel, blueprint: PipelineBlueprint) -> PipelineRun:
    """Pipeline run for deferred read endpoints."""
    return PipelineRun.objects.create(
        channel=channel,
        blueprint=blueprint,
        blueprint_snapshot={'stages': []},
        topic='Deferred API test',
    )


@pytest.mark.django_db
def test_list_blueprints(
    dmr_client: DMRClient,
    blueprint: PipelineBlueprint,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/blueprints/ returns paginated blueprint summaries."""
    response = dmr_client.get(
        reverse('api:pipelines_api:blueprint-collection'),
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body['total'] >= 1
    assert any(item['id'] == str(blueprint.id) for item in body['items'])
    assert 'next_cursor' in body


@pytest.mark.django_db
def test_list_run_assets(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """GET /api/runs/{id}/assets/ returns presigned run assets."""
    asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'video', name='clip.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=run,
    )

    with patch(
        'server.common.storage.PresignUrlHelper.presign_get',
        return_value='https://storage.example/clip.mp4',
    ):
        response = dmr_client.get(
            reverse(
                'api:pipelines_api:run-assets',
                kwargs={'run_id': run.id},
            ),
            headers=auth_headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 1
    assert body['items'][0]['id'] == str(asset.id)
    assert body['items'][0]['url'] == 'https://storage.example/clip.mp4'


@pytest.mark.django_db
def test_run_transcript_empty_without_stage(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Transcript endpoint returns empty payload when transcribe has not run."""
    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-transcript',
            kwargs={'run_id': run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body['asset_id'] is None
    assert body['words'] == []
    assert body['chapters'] == []


@pytest.mark.django_db
def test_run_transcript_from_clip_transcribe(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Transcript endpoint reads clip_transcribe stage output."""
    manifest = Asset.objects.create(
        kind=AssetKind.DOC,
        file=ContentFile(
            json.dumps(
                {
                    'enriched_transcript': [
                        {
                            'word': 'hello',
                            'start': 0.0,
                            'end': 0.5,
                            'speaker_id': 'spk_0',
                        },
                    ],
                    'scene_cuts': [12.5],
                },
            ).encode(),
            name='manifest.json',
        ),
        mime='application/json',
        checksum='manifest',
        run=run,
    )
    transcript = Asset.objects.create(
        kind=AssetKind.TRANSCRIPT,
        file=ContentFile(b'{}', name='transcript.json'),
        mime='application/json',
        checksum='transcript',
        run=run,
    )
    StageExecution.objects.create(
        run=run,
        stage_key='clip_transcribe',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={
            'transcript_asset_id': str(transcript.id),
            'manifest_asset_id': str(manifest.id),
        },
    )

    with patch(
        'server.common.storage.PresignUrlHelper.presign_get',
        return_value='https://storage.example/transcript.json',
    ):
        response = dmr_client.get(
            reverse(
                'api:pipelines_api:run-transcript',
                kwargs={'run_id': run.id},
            ),
            headers=auth_headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body['asset_id'] == str(transcript.id)
    assert body['source_asset_url'] == 'https://storage.example/transcript.json'
    assert len(body['words']) == 1
    assert body['words'][0]['word'] == 'hello'
    assert body['chapters'][0]['start_sec'] == 12.5


@pytest.mark.django_db
def test_run_transcript_missing_output_fields(
    dmr_client: DMRClient,
    run: PipelineRun,
    auth_headers: dict[str, str],
) -> None:
    """Transcript endpoint returns empty payload when stage output is incomplete."""
    StageExecution.objects.create(
        run=run,
        stage_key='clip_transcribe',
        status=StageStatus.SUCCEEDED,
        attempt=0,
        output={},
    )

    response = dmr_client.get(
        reverse(
            'api:pipelines_api:run-transcript',
            kwargs={'run_id': run.id},
        ),
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body['asset_id'] is None
    assert body['words'] == []
