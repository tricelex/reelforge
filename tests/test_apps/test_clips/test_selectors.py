"""Tests for clip selectors."""

import uuid
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile

from server.apps.assets.models import Asset, AssetKind
from server.apps.clips.models import ClipCandidate
from server.apps.clips.selectors import (
    dimensions_from_probe,
    get_asset_dimensions,
    get_candidate_source_dimensions,
    get_run_source_asset_id,
)
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    StageExecution,
    StageStatus,
)


@pytest.fixture
def candidate_with_ingest(db: None) -> tuple[ClipCandidate, Asset]:
    from server.apps.channels.models import (
        Channel,
        ChannelKind,
        PublishMode,
    )

    channel = Channel.objects.create(
        name='Selector Test',
        kind=ChannelKind.CLIPPING,
        publish_mode=PublishMode.REVIEW,
    )
    bp = PipelineBlueprint.objects.create(
        name='clipping_v1',
        kind=PipelineKind.CLIPPING,
        graph={'stages': []},
    )
    run = PipelineRun.objects.create(
        channel=channel,
        blueprint=bp,
        blueprint_snapshot={'stages': []},
        topic='https://youtube.com/watch?v=test',
    )
    asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'video', name='source.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=run,
        meta={'width': 1280, 'height': 720},
    )
    StageExecution.objects.create(
        run=run,
        stage_key='clip_ingest',
        status=StageStatus.SUCCEEDED,
        output={'asset_id': str(asset.id)},
    )
    candidate = ClipCandidate.objects.create(
        run=run,
        start_sec=0.0,
        end_sec=30.0,
        title='Selector Clip',
    )
    return candidate, asset


def test_dimensions_from_probe_video_stream() -> None:
    width, height = dimensions_from_probe(
        {
            'streams': [
                {'codec_type': 'audio'},
                {'codec_type': 'video', 'width': 1920, 'height': 1080},
            ],
        },
    )
    assert width == 1920
    assert height == 1080


def test_dimensions_from_probe_missing_video() -> None:
    width, height = dimensions_from_probe({'streams': []})
    assert width is None
    assert height is None


@pytest.mark.django_db
def test_get_run_source_asset_id(
    candidate_with_ingest: tuple[ClipCandidate, Asset],
) -> None:
    candidate, asset = candidate_with_ingest
    assert get_run_source_asset_id(str(candidate.run_id)) == str(asset.id)


@pytest.mark.django_db
def test_get_run_source_asset_id_missing(candidate_with_ingest: tuple) -> None:
    assert get_run_source_asset_id(str(uuid.uuid4())) is None


@pytest.mark.django_db
def test_get_asset_dimensions_from_meta(
    candidate_with_ingest: tuple[ClipCandidate, Asset],
) -> None:
    _, asset = candidate_with_ingest
    width, height = get_asset_dimensions(str(asset.id))
    assert width == 1280
    assert height == 720


@pytest.mark.django_db
def test_get_candidate_source_dimensions(
    candidate_with_ingest: tuple[ClipCandidate, Asset],
) -> None:
    candidate, _ = candidate_with_ingest
    width, height = get_candidate_source_dimensions(str(candidate.id))
    assert width == 1280
    assert height == 720


@pytest.mark.django_db
def test_get_asset_dimensions_probes_when_meta_missing(
    candidate_with_ingest: tuple[ClipCandidate, Asset],
) -> None:
    _, asset = candidate_with_ingest
    asset.meta = {}
    asset.save(update_fields=['meta'])

    with patch(
        'server.apps.clips.selectors.probe_local_video_dimensions',
        return_value=(640, 360),
    ):
        width, height = get_asset_dimensions(str(asset.id))

    assert width == 640
    assert height == 360
    asset.refresh_from_db()
    assert asset.meta['width'] == 640
    assert asset.meta['height'] == 360
