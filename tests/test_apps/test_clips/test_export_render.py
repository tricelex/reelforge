"""Tests for clip export rendering."""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile

from server.apps.assets.models import Asset, AssetKind
from server.apps.channels.models import Channel, ChannelKind, PublishMode
from server.apps.clips.export_render import (
    export_cache_key,
    get_export_state,
    render_clip_export_sync,
    set_export_queued,
)
from server.apps.clips.logic.constants import CandidateStatus
from server.apps.clips.models import ClipCandidate
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
        name='Bare Export',
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
        status=CandidateStatus.APPROVED,
    )


@pytest.fixture
def candidate_with_transcript(db: None) -> ClipCandidate:
    channel = Channel.objects.create(
        name='Export Test',
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
    return ClipCandidate.objects.create(
        run=run,
        start_sec=0.0,
        end_sec=30.0,
        title='Export Clip',
        status=CandidateStatus.APPROVED,
    )


@pytest.mark.django_db
def test_render_clip_export_sync_saves_final_asset(
    candidate_with_transcript: ClipCandidate,
) -> None:
    candidate = candidate_with_transcript
    set_export_queued(str(candidate.id))

    with patch(
        'server.apps.clips.export_render._run_export_pipeline',
        return_value=b'export mp4',
    ):
        render_clip_export_sync(str(candidate.id))

    candidate.refresh_from_db()
    assert candidate.render_asset_id is not None
    assert candidate.status == CandidateStatus.RENDERED
    asset = Asset.objects.get(id=candidate.render_asset_id)
    assert asset.kind == AssetKind.FINAL_VIDEO
    state = get_export_state(str(candidate.id))
    assert state is not None
    assert state['status'] == 'ready'


@pytest.mark.django_db
def test_render_clip_export_sync_missing_source(
    bare_candidate: ClipCandidate,
) -> None:
    render_clip_export_sync(str(bare_candidate.id))
    state = get_export_state(str(bare_candidate.id))
    assert state is not None
    assert state['status'] == 'failed'
    assert 'Source video' in state['error']


@pytest.mark.django_db
def test_render_clip_export_sync_missing_transcript(
    bare_candidate: ClipCandidate,
) -> None:
    source_asset = Asset.objects.create(
        kind=AssetKind.VIDEO_SEGMENT,
        file=ContentFile(b'video', name='source.mp4'),
        mime='video/mp4',
        checksum='abc',
        run=bare_candidate.run,
    )
    StageExecution.objects.create(
        run=bare_candidate.run,
        stage_key='clip_ingest',
        status=StageStatus.SUCCEEDED,
        output={'asset_id': str(source_asset.id)},
    )
    render_clip_export_sync(str(bare_candidate.id))
    state = get_export_state(str(bare_candidate.id))
    assert state is not None
    assert state['status'] == 'failed'
    assert 'Transcript' in state['error']


@pytest.mark.django_db
def test_render_clip_export_sync_pipeline_error(
    candidate_with_transcript: ClipCandidate,
) -> None:
    candidate = candidate_with_transcript

    with patch(
        'server.apps.clips.export_render._run_export_pipeline',
        side_effect=RuntimeError('ffmpeg failed'),
    ):
        render_clip_export_sync(str(candidate.id))

    state = get_export_state(str(candidate.id))
    assert state is not None
    assert state['status'] == 'failed'
    assert 'ffmpeg failed' in state['error']
    candidate.refresh_from_db()
    assert candidate.status == CandidateStatus.APPROVED


@pytest.mark.django_db
def test_run_export_pipeline_uses_format_dimensions(
    candidate_with_transcript: ClipCandidate,
) -> None:
    """The export pipeline renders at full format resolution."""
    from server.apps.clips.export_render import _run_export_pipeline
    from server.apps.clips.logic.constants import RenderFormat

    candidate = ClipCandidate.objects.select_related(
        'layout_config',
        'style_config',
        'run',
    ).get(id=candidate_with_transcript.id)
    layout = candidate.layout_config
    layout.render_format = RenderFormat.LANDSCAPE_16_9
    layout.save(update_fields=['render_format', 'updated_at'])
    candidate.refresh_from_db()

    source_asset = MagicMock()
    source_asset.checksum = 'source-checksum'
    source_asset.file.open.return_value.read = MagicMock(
        side_effect=[b'video', b''],
    )

    captured: dict[str, object] = {}

    def _fake_run(self: object) -> None:
        config = self.config  # type: ignore[attr-defined]
        captured['width'] = config.width
        captured['height'] = config.height
        captured['crf'] = config.crf
        config.output_path.write_bytes(b'rendered')

    with patch(
        'server.apps.rendering.clip_render_pipeline.ClipRenderPipeline.run',
        _fake_run,
    ):
        rendered = _run_export_pipeline(
            candidate=candidate,
            candidate_id=str(candidate.id),
            source_asset=source_asset,
            transcript_json={'segments': []},
            timed_overlays=[],
            timed_sfx=[],
        )

    assert rendered == b'rendered'
    assert captured['width'] == 1920
    assert captured['height'] == 1080
    assert captured['crf'] == 18


def test_export_cache_key_prefix() -> None:
    assert export_cache_key('abc') == 'clip_export:abc'


@pytest.mark.django_db
def test_get_export_state_ignores_non_dict() -> None:
    cache.set(export_cache_key('weird'), 'not-a-dict')
    assert get_export_state('weird') is None
