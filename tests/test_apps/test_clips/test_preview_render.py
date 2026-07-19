"""Tests for clip preview rendering."""

import json
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile

from server.apps.assets.models import Asset, AssetKind
from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.clips.models import ClipCandidate
from server.apps.clips.preview_render import (
    PREVIEW_QUEUED_STALE_SEC,
    is_preview_job_stale,
    preview_cache_key,
    preview_dimensions,
    preview_job_entry,
    render_clip_preview_sync,
)
from server.apps.pipelines.models import (
    PipelineBlueprint,
    PipelineKind,
    PipelineRun,
    StageExecution,
    StageStatus,
)


@pytest.fixture
def bare_candidate(db: None) -> ClipCandidate:
    channel = Channel.objects.create(
        name='Bare Preview',
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
    return ClipCandidate.objects.create(
        run=run,
        start_sec=0.0,
        end_sec=30.0,
        title='Bare Clip',
    )


@pytest.fixture
def candidate_with_transcript(db: None) -> tuple[ClipCandidate, Asset, Asset]:
    channel = Channel.objects.create(
        name='Preview Test',
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
    source_asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'video', name='source.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=run,
    )
    manifest_asset = Asset.objects.create(
        kind=AssetKind.DOC,
        file=ContentFile(
            json.dumps({'transcript_json': {'segments': []}}).encode(),
            name='manifest.json',
        ),
        mime='application/json',
        checksum='def',
        run=run,
    )
    StageExecution.objects.create(
        run=run,
        stage_key='clip_ingest',
        status=StageStatus.SUCCEEDED,
        output={'asset_id': str(source_asset.id)},
    )
    StageExecution.objects.create(
        run=run,
        stage_key='clip_transcribe',
        status=StageStatus.SUCCEEDED,
        output={'manifest_asset_id': str(manifest_asset.id)},
    )
    candidate = ClipCandidate.objects.create(
        run=run,
        start_sec=0.0,
        end_sec=30.0,
        title='Preview Clip',
    )
    return candidate, source_asset, manifest_asset


@pytest.mark.django_db
def test_preview_dimensions_default_vertical(
    bare_candidate: ClipCandidate,
) -> None:
    """Default layout (9:16) previews at half of 1080x1920."""
    assert preview_dimensions(bare_candidate) == (540, 960)


@pytest.mark.django_db
def test_preview_dimensions_landscape(
    bare_candidate: ClipCandidate,
) -> None:
    """A 16:9 layout previews at half of 1920x1080."""
    from server.apps.clips.logic.constants import RenderFormat

    layout = bare_candidate.layout_config
    layout.render_format = RenderFormat.LANDSCAPE_16_9
    layout.save(update_fields=['render_format', 'updated_at'])
    bare_candidate.refresh_from_db()
    assert preview_dimensions(bare_candidate) == (960, 540)


@pytest.mark.django_db
def test_preview_dimensions_without_layout_config() -> None:
    """A candidate without a layout config row falls back to 9:16."""
    assert preview_dimensions(ClipCandidate()) == (540, 960)


def test_preview_job_entry_has_timestamp() -> None:
    """New job entries carry a wall-clock timestamp for stale detection."""
    entry = preview_job_entry('queued', 42)
    assert entry['status'] == 'queued'
    assert entry['config_version'] == 42
    assert isinstance(entry['at'], float)


def test_is_preview_job_stale_ignores_terminal_states() -> None:
    """Only queued/rendering entries can go stale."""
    assert is_preview_job_stale({'status': 'ready'}) is False
    assert is_preview_job_stale({'status': 'failed'}) is False


def test_is_preview_job_stale_fresh_and_expired() -> None:
    """Fresh entries are live; expired and legacy entries are stale."""
    import time

    fresh = preview_job_entry('queued', 1)
    assert is_preview_job_stale(fresh) is False
    expired = {
        'status': 'queued',
        'at': time.time() - PREVIEW_QUEUED_STALE_SEC - 1,
    }
    assert is_preview_job_stale(expired) is True
    legacy = {'status': 'rendering'}
    assert is_preview_job_stale(legacy) is True


@pytest.mark.django_db
def test_render_clip_preview_sync_saves_asset(
    candidate_with_transcript: tuple[ClipCandidate, Asset, Asset],
) -> None:
    candidate, _, _ = candidate_with_transcript
    cache.set(preview_cache_key(str(candidate.id)), {'status': 'queued'})

    with patch(
        'server.apps.clips.preview_render._run_preview_pipeline',
        return_value=b'preview mp4',
    ):
        render_clip_preview_sync(str(candidate.id))

    candidate.refresh_from_db()
    assert candidate.preview_asset_id is not None
    cached = cache.get(preview_cache_key(str(candidate.id)))
    assert cached is not None
    assert cached['status'] == 'ready'
    assert 'config_version' in cached


@pytest.mark.django_db
def test_render_clip_preview_sync_skips_when_already_ready(
    candidate_with_transcript: tuple[ClipCandidate, Asset, Asset],
) -> None:
    """Worker exits early when a fresh preview is already cached."""
    from server.apps.clips.preview_render import preview_config_version

    candidate, _, _ = candidate_with_transcript
    preview_asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'preview', name='preview.mp4'),
        mime='video/mp4',
        checksum='prev',
        run=candidate.run,
    )
    candidate.preview_asset_id = preview_asset.id
    candidate.save(update_fields=['preview_asset_id'])
    version = preview_config_version(str(candidate.id))
    cache.set(
        preview_cache_key(str(candidate.id)),
        {'status': 'ready', 'config_version': version},
    )

    with patch(
        'server.apps.clips.preview_render._run_preview_pipeline',
    ) as mock_pipeline:
        render_clip_preview_sync(str(candidate.id))

    mock_pipeline.assert_not_called()


@pytest.mark.django_db
def test_render_clip_preview_sync_missing_source(
    bare_candidate: ClipCandidate,
) -> None:
    render_clip_preview_sync(str(bare_candidate.id))
    cached = cache.get(preview_cache_key(str(bare_candidate.id)))
    assert cached is not None
    assert cached['status'] == 'failed'


@pytest.mark.django_db
def test_render_clip_preview_sync_pipeline_error(
    candidate_with_transcript: tuple[ClipCandidate, Asset, Asset],
) -> None:
    candidate, _, _ = candidate_with_transcript

    with patch(
        'server.apps.clips.preview_render._run_preview_pipeline',
        side_effect=RuntimeError('ffmpeg failed'),
    ):
        render_clip_preview_sync(str(candidate.id))

    cached = cache.get(preview_cache_key(str(candidate.id)))
    assert cached is not None
    assert cached['status'] == 'failed'
    assert 'ffmpeg failed' in cached['error']
